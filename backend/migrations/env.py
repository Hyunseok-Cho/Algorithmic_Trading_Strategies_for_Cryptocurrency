"""Alembic migration environment for the CLI's PostgreSQL database."""

from logging.config import fileConfig

from alembic import context

from trading_lab.config import Settings
from trading_lab.infrastructure.database.engine import build_engine
from trading_lab.infrastructure.database.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Render PostgreSQL SQL without credentials, a driver or a DB connection.

    This compiles revision scripts; it cannot inspect the database, validate
    existing data or establish that the generated SQL succeeds on PostgreSQL.
    """
    context.configure(
        dialect_name="postgresql",
        dialect_opts={"paramstyle": "named"},
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply revisions using the same validated configuration as the CLI.

    Pass an SQLAlchemy URL object via build_engine instead of storing a URL
    in the INI configuration, preserving passwords containing % or @.
    Dispose the engine even when connecting or applying a revision fails.
    """
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        configure_connection(supplied_connection)
        return  # The caller owns this connection and its transaction.
    engine = build_engine(Settings())
    try:
        with engine.connect() as connection:
            configure_connection(connection)
    finally:
        engine.dispose()


def configure_connection(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
