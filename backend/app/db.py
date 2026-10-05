import time
from pathlib import Path

import psycopg
from psycopg.adapt import Loader
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from . import config


class _NumericAsFloat(Loader):
    def load(self, data):
        return float(bytes(data))


psycopg.adapters.register_loader("numeric", _NumericAsFloat)

pool: ConnectionPool | None = None


def init_pool(retries: int = 30) -> None:
    """Open the pool, waiting for Postgres to come up."""
    global pool
    last = None
    for _ in range(retries):
        try:
            p = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=12,
                               kwargs={"row_factory": dict_row}, open=False)
            p.open(wait=True, timeout=5)
            pool = p
            return
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1)
    raise RuntimeError(f"database unavailable: {last}")


def conn():
    """Transaction-scoped connection: commits on success, rolls back on error."""
    assert pool is not None, "pool not initialised"
    return pool.connection()


def migrate() -> None:
    sql_dir = Path(__file__).parent / "migrations"
    with conn() as c:
        c.execute("SELECT pg_advisory_xact_lock(727272)")
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
        done = {r["name"] for r in c.execute("SELECT name FROM schema_migrations").fetchall()}
        for f in sorted(sql_dir.glob("*.sql")):
            if f.name not in done:
                c.execute(f.read_text())
                c.execute("INSERT INTO schema_migrations(name) VALUES (%s)", (f.name,))


def audit(c, event: str, entity_type: str | None = None, entity_id: str | None = None,
          details: dict | None = None) -> None:
    c.execute(
        "INSERT INTO audit_logs(event, entity_type, entity_id, details) VALUES (%s,%s,%s,%s)",
        (event, entity_type, entity_id, Jsonb(details or {})),
    )
