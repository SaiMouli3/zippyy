"""PostgreSQL-only checks: migrations are repeatable, row-level security isolates tenants, and pooled connections
never leak tenant context. Run with TEST_POSTGRES_URL=postgresql+psycopg://user:pass@host:port/empty_db
(the database is wiped)."""
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

PG = os.environ.get("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not PG, reason="set TEST_POSTGRES_URL to run PostgreSQL tests")


@pytest.fixture(scope="module")
def pg():
    engine = create_engine(PG, pool_size=2, max_overflow=0)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    env = {**os.environ, "DATABASE_URL": PG}
    backend = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    for _ in range(2):  # repeatable: the second run must be a no-op
        out = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend, env=env,
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
    yield engine
    engine.dispose()


def _session(engine, tenant=None, system=False):
    s = sessionmaker(bind=engine)()
    s.info["tenant"] = tenant
    s.info["system"] = system
    return s


def _two_tenants(engine):
    from app.platform.models import Customer, Merchant
    from app.platform.security import crypto
    s = _session(engine, system=True)
    ids = []
    for code in ("PG-A", "PG-B"):
        m = Merchant(code=code, legal_name=code, brand_name=code)
        s.add(m)
        s.flush()
        phone = "+91900000" + ("1111" if code == "PG-A" else "2222")
        s.add(Customer(merchant_id=m.id, name=f"cust {code}", phone_enc=crypto.encrypt(phone, "customers.phone"),
                       phone_hash=crypto.phone_hash(phone), phone_last4=phone[-4:]))
        ids.append(m.id)
    s.commit()
    s.close()
    return ids


def test_schema_has_rls_on_tenant_tables(pg):
    with pg.connect() as c:
        rows = dict(c.execute(text("select relname, relforcerowsecurity from pg_class where relname in "
                                   "('ndr_cases','customers','messages','audit_logs','jobs')")).all())
    assert rows["ndr_cases"] and rows["customers"] and rows["messages"] and rows["audit_logs"]
    assert rows["jobs"] is False  # global work queue, accessed only by the worker in system context


def test_rls_isolates_tenants_and_blocks_cross_tenant_writes(pg):
    from app.platform.models import Customer
    a, b = _two_tenants(pg)
    s = _session(pg, tenant=a)
    names = [n for (n,) in s.execute(select(Customer.name))]
    assert names == ["cust PG-A"]  # even without a WHERE clause
    s.close()
    s = _session(pg, tenant=a)
    with pytest.raises(DBAPIError):
        s.add(Customer(merchant_id=b, name="smuggled", phone_enc="x", phone_hash="h" * 64, phone_last4="0000"))
        s.flush()
    s.rollback()
    s.close()
    s = _session(pg)  # no tenant, no system: sees nothing
    assert s.scalar(select(func.count()).select_from(Customer)) == 0
    s.close()


def test_pooled_connections_do_not_leak_tenant_context(pg):
    from app.platform.models import Customer
    for _ in range(3):  # pool of 2 connections: the same connection is reused
        s = _session(pg, tenant=None)
        assert s.scalar(select(func.count()).select_from(Customer)) == 0
        s.close()
        s = _session(pg, system=True)
        merchants = [m for (m,) in s.execute(text("select id from merchants where code like 'PG-%'"))]
        s.close()
        s = _session(pg, tenant=merchants[0])
        assert s.scalar(select(func.count()).select_from(Customer)) == 1
        s.commit()
        s.close()
    with pg.connect() as c:
        assert c.execute(text("select current_setting('app.merchant_id', true)")).scalar() in (None, "")


def test_append_only_history_cannot_be_rewritten_by_the_app_role(pg):
    with pg.begin() as c:
        has_role = c.execute(text("select 1 from pg_roles where rolname = 'zippy_app'")).scalar()
        if not has_role:
            pytest.skip("zippy_app role not created (migrating user lacks CREATEROLE)")
        c.execute(text("SET LOCAL ROLE zippy_app"))
        c.execute(text("select set_config('app.system','on',true)"))
        c.execute(text("insert into audit_logs (merchant_id, actor_type, entity_type, entity_id, action, created_at) "
                       "values (null, 'system', 'test', 'x', 'test.write', now())"))
    with pytest.raises(DBAPIError):
        with pg.begin() as c:
            c.execute(text("SET LOCAL ROLE zippy_app"))
            c.execute(text("select set_config('app.system','on',true)"))
            c.execute(text("delete from audit_logs where action = 'test.write'"))
