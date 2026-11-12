"""Explicit engine/session factories; no global connections or schema creation."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from trading_lab.config import Settings


def build_engine(settings: Settings) -> Engine:
    """Create a lazy PostgreSQL engine, without checking out a connection.

    The CLI owns this engine and must call engine.dispose() in its cleanup
    block. Schema changes belong to Alembic, never to application startup.
    """
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        hide_parameters=True,
        echo=False,
        connect_args={
            "connect_timeout": 10,
            "options": "-c timezone=UTC",
        },
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create independent sessions; never share one session across workers.

    Keep loaded values usable after commit/close without implicitly opening
    another transaction. Unloaded attributes still require an active session;
    services should return domain objects or DTOs rather than ORM rows.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def transaction(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit on success; roll back on any exception; always close the session.

    Each block is an independent transaction, not a nested savepoint. Do not
    call commit/rollback inside it. Sync services should use one block per
    fetched page and write the page plus its resume cursor atomically.

    Fetch exchange data before entering this block so network retries never
    hold a DB transaction open. A failed block rolls back its own writes only;
    record failure status in a separate transaction after catching the error.
    Connection loss during a transaction is propagated, never auto-replayed.
    """
    with session_factory.begin() as session:
        yield session
