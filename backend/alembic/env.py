"""Alembic environment.

Uses the sync DSN derived from `Settings` and pulls metadata from
`app.db.base.Base` after importing every model.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context
from app.core.config import get_settings
from app.db.base import Base, import_all_models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL_SYNC)

import_all_models()
target_metadata = Base.metadata

# Arbitrary but stable 64-bit key for the session-level advisory lock that
# serializes concurrent `alembic upgrade head` runs (e.g. multiple API
# replicas booting at once on Railway). Any process already migrating holds
# this lock; others block here instead of racing the version table.
_MIGRATION_LOCK_KEY = 0x456E676167654F53  # "EngageOS" as hex


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            version_table_schema="public",
        )
        # Serialize concurrent migrators. pg_advisory_lock is session-scoped and
        # blocks (does not error) until the lock is free. Acquired inside the
        # alembic-managed transaction so that begin_transaction() starts a fresh
        # transaction (SQLAlchemy 2.0 autobegin would make it a no-op proxy if
        # any execute occurred before begin_transaction(), causing migrations to
        # run but never commit).
        with context.begin_transaction():
            connection.execute(
                text("SELECT pg_advisory_lock(:k)"), {"k": _MIGRATION_LOCK_KEY}
            )
            try:
                context.run_migrations()
            finally:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": _MIGRATION_LOCK_KEY}
                )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
