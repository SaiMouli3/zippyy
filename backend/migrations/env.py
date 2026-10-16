"""Alembic environment. Migrations target PostgreSQL (the production database); unit tests on SQLite create
tables from the models directly."""
from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings

config = context.config


def run_migrations_online() -> None:
    url = get_settings().database_url
    if not url.startswith("postgresql"):
        raise SystemExit("Alembic migrations target PostgreSQL; set DATABASE_URL to a postgresql+psycopg:// URL")
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    context.configure(url=get_settings().database_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
