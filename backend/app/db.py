"""Engine, sessions and tenant context.

Tenant isolation is enforced twice:
1. Every platform query filters on merchant_id explicitly (services take it from the authenticated context).
2. On Postgres, row-level security (migration 0003) checks `app.merchant_id`, which is set with
   `set_config(..., is_local => true)` at the start of *every* transaction. Transaction-local settings vanish
   at COMMIT/ROLLBACK, so a pooled connection can never leak one tenant's context into another request.

`system_context()` is used only by narrow internal code paths that must look across tenants before a tenant
is known (webhook AWB lookup, the job claimer, schedulers). It is never reachable from a user request.
"""
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None

_tenant: ContextVar[str | None] = ContextVar("tenant", default=None)
_system: ContextVar[bool] = ContextVar("system", default=False)


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        if url.startswith("sqlite"):
            kwargs = {"connect_args": {"check_same_thread": False}}
        else:
            kwargs = {
                "pool_pre_ping": True,
                "pool_size": settings.db_pool_size,
                "max_overflow": settings.db_max_overflow,
                "pool_recycle": 1800,
            }
        _engine = create_engine(url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    """Tests switch DATABASE_URL between SQLite and Postgres."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_session_factory() -> sessionmaker:
    get_engine()
    return _SessionLocal


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(session: Session, transaction, connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    tenant = session.info.get("tenant", _tenant.get())
    system = session.info.get("system", _system.get())
    connection.execute(
        text("SELECT set_config('app.merchant_id', :m, true), set_config('app.system', :s, true)"),
        {"m": tenant or "", "s": "on" if system else "off"},
    )


def bind_tenant(session: Session, merchant_id: str | None) -> None:
    """Pin a session to a tenant. Takes effect from the next transaction (callers bind before querying)."""
    session.info["tenant"] = merchant_id
    session.info["system"] = False


@contextmanager
def tenant_context(merchant_id: str):
    token = _tenant.set(merchant_id)
    sys_token = _system.set(False)
    try:
        yield
    finally:
        _tenant.reset(token)
        _system.reset(sys_token)


@contextmanager
def system_context():
    token = _system.set(True)
    try:
        yield
    finally:
        _system.reset(token)


def new_session(merchant_id: str | None = None, system: bool = False) -> Session:
    db = get_session_factory()()
    db.info["tenant"] = merchant_id
    db.info["system"] = system
    return db


def get_db() -> Iterator[Session]:
    """Legacy MVP routes: no tenant (sandbox rows have no merchant_id)."""
    db = new_session(system=True)
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Development convenience: create tables directly on SQLite. Postgres uses Alembic migrations."""
    from app import models  # noqa: F401  (register tables)
    from app.platform import models as platform_models  # noqa: F401

    Base.metadata.create_all(get_engine())
