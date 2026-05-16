"""Alembic env script — async-aware.

Drives SQLAlchemy 2.x async migrations against asyncpg. Reads DATABASE_URL
from env (or falls back to the docker-compose default) so the same script
runs locally + in deploy.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Ensure `api.*` is importable when alembic is invoked from the api/ dir.
import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parent.parent  # .../api
_REPO_ROOT = _API_DIR.parent
for p in (str(_REPO_ROOT), str(_API_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from api.db.base import Base  # noqa: E402
import api.db.models  # noqa: F401, E402  -- registers tables on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Resolve DATABASE_URL: env var wins; fall back to docker-compose default.
_db_url = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://goti:goti@localhost:5432/goti",
)
# Alembic + SQLAlchemy 2.x async requires the `+asyncpg` driver in the URL.
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
config.set_main_option("sqlalchemy.url", _db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
