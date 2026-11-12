"""Offline migration checks, not a substitute for PostgreSQL integration tests."""

import io
import re
import runpy
from unittest.mock import MagicMock, Mock

import pytest
import sqlalchemy as sa
from alembic import command, context, op
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint, CreateColumn, CreateIndex

from trading_lab.config import BACKEND_DIR
from trading_lab.infrastructure.database.models import Base

REVISION = "0001_initial_schema"
TABLES = (
    "markets",
    "candles",
    "funding_rates",
    "sync_jobs",
    "data_coverage",
    "backtest_runs",
    "backtest_trades",
)


@pytest.fixture
def migration_config(monkeypatch):
    # Loading env.py must not reconfigure pytest's process-wide logging.
    monkeypatch.setattr("logging.config.fileConfig", Mock())
    return Config(str(BACKEND_DIR / "alembic.ini"), output_buffer=io.StringIO())


@pytest.fixture
def offline_sql(migration_config, monkeypatch):
    # Fail immediately if offline SQL generation ever starts reading credentials
    # or constructing a database engine, even when a real local .env exists.
    monkeypatch.setattr(
        "trading_lab.config.Settings",
        Mock(side_effect=AssertionError("Offline migrations must not read credentials")),
    )
    monkeypatch.setattr(
        "trading_lab.infrastructure.database.engine.build_engine",
        Mock(side_effect=AssertionError("Offline migrations must not build a DB engine")),
    )
    command.upgrade(migration_config, "head", sql=True)
    upgrade_sql = migration_config.output_buffer.getvalue()
    migration_config.output_buffer = io.StringIO()
    command.downgrade(migration_config, f"{REVISION}:base", sql=True)
    return upgrade_sql, migration_config.output_buffer.getvalue()


def test_revision_chain_has_one_initial_head(migration_config):
    scripts = ScriptDirectory.from_config(migration_config)
    assert scripts.get_heads() == [REVISION]
    assert scripts.get_revision(REVISION).down_revision is None


def test_upgrade_renders_all_tables_and_indexes_without_credentials(offline_sql):
    upgrade_sql, _ = offline_sql
    tables = set(re.findall(r"CREATE TABLE (\w+)\s*\(", upgrade_sql))
    assert tables == set(TABLES) | {"alembic_version"}
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            assert f"CREATE INDEX {index.name} ON {table.name}" in upgrade_sql
    assert "TIMESTAMP WITH TIME ZONE" in upgrade_sql
    assert "JSONB" in upgrade_sql


def test_downgrade_renders_drops_in_foreign_key_order_without_executing_them(offline_sql):
    _, downgrade_sql = offline_sql
    dropped = re.findall(r"DROP TABLE (\w+);", downgrade_sql)
    assert len(dropped) == len(TABLES)
    assert set(dropped) == set(TABLES)
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            assert dropped.index(table.name) < dropped.index(foreign_key.column.table.name)


@pytest.fixture
def initial_schema_snapshot(migration_config, monkeypatch):
    snapshot = sa.MetaData(naming_convention=Base.metadata.naming_convention)
    revision = ScriptDirectory.from_config(migration_config).get_revision(REVISION)

    def capture_table(name, *elements, **kwargs):
        return sa.Table(name, snapshot, *elements, **kwargs)

    def capture_index(name, table_name, columns, **kwargs):
        return sa.Index(
            name, *[snapshot.tables[table_name].c[column] for column in columns], **kwargs
        )

    monkeypatch.setattr(op, "create_table", capture_table)
    monkeypatch.setattr(op, "create_index", capture_index)
    migration_context = MigrationContext.configure(
        dialect_name="postgresql", opts={"target_metadata": Base.metadata}
    )
    with Operations.context(migration_context):
        revision.module.upgrade()
    assert set(snapshot.tables) == set(TABLES)
    return snapshot


def schema_signature(table):
    dialect = postgresql.dialect()
    return (
        tuple(str(CreateColumn(column).compile(dialect=dialect)) for column in table.columns),
        frozenset(str(AddConstraint(item).compile(dialect=dialect)) for item in table.constraints),
        frozenset(str(CreateIndex(index).compile(dialect=dialect)) for index in table.indexes),
    )


@pytest.mark.parametrize("table_name", TABLES)
def test_initial_revision_matches_current_orm(initial_schema_snapshot, table_name):
    # When adding later revisions, extend this check to apply the full chain.
    assert schema_signature(initial_schema_snapshot.tables[table_name]) == schema_signature(
        Base.metadata.tables[table_name]
    )


@pytest.mark.parametrize("failure_stage", [None, "connect", "migration"])
def test_online_environment_always_disposes_engine(migration_config, monkeypatch, failure_stage):
    engine = MagicMock()
    failure = RuntimeError("Deliberate migration failure")
    if failure_stage == "connect":
        engine.connect.side_effect = failure

    settings = Mock()
    settings_constructor = Mock(return_value=settings)
    engine_builder = Mock(return_value=engine)
    run_migrations = Mock(side_effect=failure if failure_stage == "migration" else None)
    monkeypatch.setattr("trading_lab.config.Settings", settings_constructor)
    monkeypatch.setattr("trading_lab.infrastructure.database.engine.build_engine", engine_builder)
    monkeypatch.setattr(context, "config", migration_config, raising=False)
    monkeypatch.setattr(context, "is_offline_mode", Mock(return_value=False))
    monkeypatch.setattr(context, "configure", Mock())
    monkeypatch.setattr(context, "begin_transaction", MagicMock())
    monkeypatch.setattr(context, "run_migrations", run_migrations)

    if failure_stage is None:
        runpy.run_path(str(BACKEND_DIR / "migrations" / "env.py"))
    else:
        with pytest.raises(RuntimeError) as captured:
            runpy.run_path(str(BACKEND_DIR / "migrations" / "env.py"))
        assert captured.value is failure

    engine.dispose.assert_called_once_with()
    settings_constructor.assert_called_once_with()
    engine_builder.assert_called_once_with(settings)
    assert run_migrations.call_count == (0 if failure_stage == "connect" else 1)
