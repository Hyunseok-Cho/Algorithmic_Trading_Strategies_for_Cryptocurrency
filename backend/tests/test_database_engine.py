"""Offline transaction tests; SQLite does not validate PostgreSQL schema behavior."""

from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError

from trading_lab.config import Settings
from trading_lab.infrastructure.database.engine import (
    build_engine,
    build_session_factory,
    transaction,
)


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)"))
            connection.execute(
                text("CREATE TABLE sync_cursor (id INTEGER PRIMARY KEY, page INTEGER)")
            )
            connection.execute(text("INSERT INTO sync_cursor VALUES (1, 0)"))

        factory = build_session_factory(engine)
        closed_sessions = []
        original_close = factory.class_.close

        def track_close(session):
            try:
                return original_close(session)
            finally:
                closed_sessions.append(session)

        monkeypatch.setattr(factory.class_, "close", track_close)
        yield engine, factory, closed_sessions
    finally:
        engine.dispose()


def test_postgres_factory_passes_credentials_and_connection_policy_without_connecting(monkeypatch):
    # Explicit values keep the test independent of developer .env and shell settings.
    settings = Settings(
        _env_file=None,
        POSTGRES_DB="test_db",
        POSTGRES_USER="test_user",
        POSTGRES_PASSWORD="test@pass/word",
        POSTGRES_HOST="127.0.0.1",
        POSTGRES_PORT=55432,
    )
    constructor = Mock()
    monkeypatch.setattr("trading_lab.infrastructure.database.engine.create_engine", constructor)

    engine = build_engine(settings)

    assert engine is constructor.return_value
    constructor.assert_called_once()
    url = constructor.call_args.args[0]
    assert url.drivername == "postgresql+psycopg"
    assert (url.host, url.port, url.database) == ("127.0.0.1", 55432, "test_db")
    assert url.password == "test@pass/word"
    options = constructor.call_args.kwargs
    assert options["pool_pre_ping"] is True
    assert options["hide_parameters"] is True
    assert options["echo"] is False
    assert options["connect_args"] == {"connect_timeout": 10, "options": "-c timezone=UTC"}


def test_success_commits_and_closes_session(database):
    engine, factory, closed = database

    with transaction(factory) as session:
        session.execute(text("INSERT INTO records VALUES (1, 'saved')"))
        assert session not in closed

    assert closed == [session]
    assert not session.in_transaction()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT value FROM records")).scalar_one() == "saved"


@pytest.mark.parametrize("failure", [RuntimeError("operation failed"), KeyboardInterrupt()])
def test_exception_rolls_back_closes_and_propagates(database, failure):
    engine, factory, closed = database

    with pytest.raises(type(failure)) as captured:
        with transaction(factory) as session:
            session.execute(text("INSERT INTO records VALUES (1, 'discarded')"))
            raise failure

    assert captured.value is failure
    assert closed == [session]
    assert not session.in_transaction()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM records")).scalar_one() == 0


def test_database_error_rolls_back_the_entire_page_and_cursor(database):
    engine, factory, closed = database

    with pytest.raises(IntegrityError):
        with transaction(factory) as session:
            session.execute(text("INSERT INTO records VALUES (1, 'first')"))
            session.execute(text("UPDATE sync_cursor SET page = 1 WHERE id = 1"))
            session.execute(text("INSERT INTO records VALUES (1, 'duplicate')"))

    assert closed == [session]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM records")).scalar_one() == 0
        assert connection.execute(text("SELECT page FROM sync_cursor")).scalar_one() == 0


def test_commit_failure_rolls_back_and_does_not_retry(database):
    engine, factory, closed = database
    failure = RuntimeError("commit rejected")
    commit_attempts = []

    def reject_commit(session):
        commit_attempts.append(session)
        raise failure

    event.listen(factory.class_, "before_commit", reject_commit)
    try:
        with pytest.raises(RuntimeError) as captured:
            with transaction(factory) as session:
                session.execute(text("INSERT INTO records VALUES (1, 'discarded')"))
    finally:
        event.remove(factory.class_, "before_commit", reject_commit)

    assert captured.value is failure
    assert commit_attempts == [session]
    assert closed == [session]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM records")).scalar_one() == 0


def test_later_failure_preserves_previously_committed_page(database):
    engine, factory, closed = database
    with transaction(factory) as first:
        first.execute(text("INSERT INTO records VALUES (1, 'page one')"))
        first.execute(text("UPDATE sync_cursor SET page = 1 WHERE id = 1"))

    with pytest.raises(RuntimeError):
        with transaction(factory) as second:
            second.execute(text("INSERT INTO records VALUES (2, 'page two')"))
            second.execute(text("UPDATE sync_cursor SET page = 2 WHERE id = 1"))
            raise RuntimeError("page two failed")

    assert first is not second
    assert closed == [first, second]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM records")).scalars().all() == [1]
        assert connection.execute(text("SELECT page FROM sync_cursor")).scalar_one() == 1
