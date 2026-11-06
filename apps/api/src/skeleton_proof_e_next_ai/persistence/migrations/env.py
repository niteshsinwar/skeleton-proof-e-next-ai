"""Alembic environment: synchronous psycopg connection, URL from the process settings (02/D2).

Alembic loads this file outside the package, so imports are absolute (alembic.ini prepends src/).
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from skeleton_proof_e_next_ai.config.settings import get_settings
from skeleton_proof_e_next_ai.persistence.schema import metadata

url = context.config.get_main_option("sqlalchemy.url") or get_settings().database_url

connectable = create_engine(url, poolclass=pool.NullPool)
with connectable.connect() as connection:
    context.configure(
        connection=connection, target_metadata=metadata, include_schemas=True, transaction_per_migration=True
    )
    with context.begin_transaction():
        context.run_migrations()
