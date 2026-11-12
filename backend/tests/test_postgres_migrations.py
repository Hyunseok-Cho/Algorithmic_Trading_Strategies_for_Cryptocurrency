"""Explicit integration check: actual Alembic upgrade/downgrade in a disposable schema."""

import io
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from trading_lab.config import BACKEND_DIR
from trading_lab.infrastructure.database.models import Base


@pytest.mark.integration
def test_postgres_actual_migration_upgrade_and_downgrade():
    url = os.environ.get("TRADING_LAB_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set a dedicated PostgreSQL test database URL")
    engine = create_engine(url, hide_parameters=True)
    schema = f"trading_lab_migration_{uuid4().hex}"
    try:
        if engine.dialect.name != "postgresql":
            raise ValueError("A PostgreSQL test DB is required")
        with engine.connect() as connection, connection.begin():
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            config = Config(str(BACKEND_DIR / "alembic.ini"), stdout=io.StringIO())
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            tables = set(inspect(connection).get_table_names(schema=schema))
            assert tables == set(Base.metadata.tables) | {"alembic_version"}
            command.downgrade(config, "base")
            assert inspect(connection).get_table_names(schema=schema) == ["alembic_version"]
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        engine.dispose()
