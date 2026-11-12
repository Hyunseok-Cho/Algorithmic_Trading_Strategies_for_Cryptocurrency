"""Offline repository checks plus opt-in tests against a dedicated PostgreSQL DB.

Mocked SQL checks do not establish database idempotency. The integration tests
below exercise it only when explicitly selected and supplied a test DB URL.
"""

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from trading_lab.domain.enums import MarketType
from trading_lab.domain.exceptions import DataCoverageError, InvalidMarketDataError, RepositoryError
from trading_lab.domain.interfaces import WriteCounts
from trading_lab.domain.models import Candle, FundingRate, Market
from trading_lab.infrastructure.database.engine import build_session_factory, transaction
from trading_lab.infrastructure.database.models import Base
from trading_lab.infrastructure.database.repositories import PostgresMarketDataRepository

START = datetime(2026, 10, 31, tzinfo=UTC)
END = START + timedelta(hours=2)


@pytest.fixture
def spot():
    return Market("binance", MarketType.SPOT, "BTC/USDT", "BTCUSDT", "BTC", "USDT")


@pytest.fixture
def perpetual():
    return Market(
        "binance",
        MarketType.PERPETUAL,
        "BTC/USDT:USDT",
        "BTCUSDT",
        "BTC",
        "USDT",
        settle_asset="USDT",
        contract_size=Decimal("1"),
    )


@pytest.fixture
def candle():
    return Candle(
        START, Decimal("100"), Decimal("110"), Decimal("90"), Decimal("105"), Decimal("0")
    )


@pytest.fixture
def session():
    return MagicMock(spec=Session)


def response(rows=(), scalar=None):
    result = MagicMock()
    result.__iter__.return_value = iter(rows)
    result.scalar_one_or_none.return_value = scalar
    result.scalar_one.return_value = scalar
    result.mappings.return_value.__iter__.return_value = iter(rows)
    result.mappings.return_value.one_or_none.return_value = rows[0] if rows else None
    return result


def compile_query(statement):
    return statement.compile(dialect=postgresql.dialect())


def assert_transaction_untouched(session):
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.close.assert_not_called()


def test_empty_input_does_not_access_database(session, spot, perpetual):
    repo = PostgresMarketDataRepository(session)
    assert repo.upsert_candles(spot, "1h", []) == WriteCounts(0, 0)
    assert repo.upsert_funding_rates(perpetual, []) == WriteCounts(0, 0)
    session.execute.assert_not_called()


@pytest.mark.parametrize("dataset", ["candles", "funding"])
def test_conflicting_duplicates_are_rejected_before_any_sql(
    session, spot, perpetual, candle, dataset
):
    repo = PostgresMarketDataRepository(session)
    with pytest.raises(InvalidMarketDataError):
        if dataset == "candles":
            repo.upsert_candles(spot, "1h", [candle, replace(candle, close=Decimal("104"))])
        else:
            rate = FundingRate(START, Decimal("0.0001"), "binance")
            repo.upsert_funding_rates(perpetual, [rate, replace(rate, rate=Decimal("0.0002"))])
    session.execute.assert_not_called()


def test_unaligned_candle_is_rejected_before_sql(session, spot, candle):
    with pytest.raises(InvalidMarketDataError):
        PostgresMarketDataRepository(session).upsert_candles(
            spot, "1h", [replace(candle, open_time=START + timedelta(minutes=1))]
        )
    session.execute.assert_not_called()


def test_identical_duplicates_are_submitted_once_and_results_are_closed(session, spot, candle):
    inserted, changed = response([(START,)]), response()
    session.execute.side_effect = [response(scalar=1), inserted, changed]
    repo = PostgresMarketDataRepository(session)

    assert repo.upsert_candles(spot, "1h", [candle, candle]) == WriteCounts(1, 0)

    insert_sql = compile_query(session.execute.call_args_list[1].args[0])
    update_sql = str(compile_query(session.execute.call_args_list[2].args[0]))
    assert len(insert_sql.params) == 8  # One candle: identity plus OHLCV.
    assert "ON CONFLICT (market_id, timeframe, open_time) DO NOTHING" in str(insert_sql)
    assert "IS DISTINCT FROM" in update_sql
    inserted.close.assert_called_once()
    changed.close.assert_called_once()
    assert_transaction_untouched(session)


def test_large_pages_are_chunked_without_committing(session, spot, candle):
    candles = [replace(candle, open_time=START + timedelta(hours=index)) for index in range(501)]
    results = [
        response([(index,) for index in range(500)]),
        response(),
        response([(500,)]),
        response(),
    ]
    session.execute.side_effect = [response(scalar=1), *results]

    counts = PostgresMarketDataRepository(session).upsert_candles(spot, "1h", candles)

    assert counts == WriteCounts(501, 0)
    assert session.execute.call_count == 5  # Market lookup, two insert/update batches.
    for result in results:
        result.close.assert_called_once()
    assert_transaction_untouched(session)


def test_null_funding_mark_price_has_explicit_numeric_type(session, perpetual):
    session.execute.side_effect = [response(scalar=2), response(), response([(START,)])]
    rate = FundingRate(START, Decimal("-0.0001"), "binance")

    counts = PostgresMarketDataRepository(session).upsert_funding_rates(perpetual, [rate])

    assert counts == WriteCounts(0, 1)
    sql = str(compile_query(session.execute.call_args_list[-1].args[0]))
    assert "CAST(NULL AS NUMERIC)" in sql
    assert "IS DISTINCT FROM" in sql


@pytest.mark.parametrize("operation", ["write", "latest", "read"])
def test_spot_funding_access_is_rejected_without_sql(session, spot, operation):
    repo = PostgresMarketDataRepository(session)
    with pytest.raises(ValueError):
        if operation == "write":
            repo.upsert_funding_rates(spot, [])
        elif operation == "latest":
            repo.latest_funding_time(spot, before=END)
        else:
            list(repo.iter_funding_rates(spot, start=START, end=END))
    session.execute.assert_not_called()


def test_missing_local_market_raises_coverage_error(session, spot):
    session.execute.return_value = response()
    with pytest.raises(DataCoverageError):
        PostgresMarketDataRepository(session).latest_candle_time(spot, "1h", before=END)


def test_market_registration_does_not_invent_first_availability(session, spot):
    PostgresMarketDataRepository(session).save_market(spot)
    sql = compile_query(session.execute.call_args.args[0])
    assert "first_available_at" not in sql.params
    assert "IS DISTINCT FROM" in str(sql)
    assert_transaction_untouched(session)


@pytest.mark.parametrize("operation", ["candles", "times", "funding"])
def test_streams_use_half_open_range_ordering_and_close_results(
    session, spot, perpetual, operation
):
    row = dict(
        open_time=START,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("0"),
        funding_time=START,
        funding_rate=Decimal("-0.0001"),
        source="binance",
        mark_price=None,
    )
    result = response([row])
    session.execute.side_effect = [response(scalar=1), result]
    repo = PostgresMarketDataRepository(session)
    if operation == "candles":
        records = list(repo.iter_candles(spot, "1h", start=START, end=END))
        assert records[0].close == Decimal("105")
    elif operation == "times":
        records = list(repo.iter_candle_times(spot, "1h", start=START, end=END))
        assert records == [START]
    else:
        records = list(repo.iter_funding_rates(perpetual, start=START, end=END))
        assert records[0].rate == Decimal("-0.0001")
        assert records[0].mark_price is None
    statement = session.execute.call_args.args[0]
    sql = compile_query(statement)
    assert START in sql.params.values() and END in sql.params.values()
    assert ">=" in str(sql) and " < " in str(sql) and "ORDER BY" in str(sql)
    assert statement.get_execution_options()["yield_per"] == 1000
    result.close.assert_called_once()
    assert_transaction_untouched(session)


def test_invalid_stored_candle_is_rejected_and_cursor_closed(session, spot):
    row = dict(
        open_time=START,
        open=Decimal("100"),
        high=Decimal("99"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("1"),
    )
    result = response([row])
    session.execute.side_effect = [response(scalar=1), result]
    with pytest.raises(InvalidMarketDataError):
        list(PostgresMarketDataRepository(session).iter_candles(spot, "1h", start=START, end=END))
    result.close.assert_called_once()


def test_database_errors_are_chained_without_exposing_raw_message(session, spot):
    failure = DBAPIError("SELECT ...", {}, RuntimeError("private connection details"))
    session.execute.side_effect = failure
    with pytest.raises(RepositoryError) as captured:
        PostgresMarketDataRepository(session).find_market(
            spot.exchange, spot.market_type, spot.symbol
        )
    assert captured.value.__cause__ is failure
    assert "private connection details" not in str(captured.value)
    assert_transaction_untouched(session)


def test_unexpected_errors_are_not_reclassified(session, spot):
    failure = RuntimeError("Programming error")
    session.execute.side_effect = failure
    with pytest.raises(RuntimeError) as captured:
        PostgresMarketDataRepository(session).save_market(spot)
    assert captured.value is failure


@pytest.fixture
def postgres_factory():
    """Opt-in real DB checks use a unique schema and never touch the public schema."""
    url = os.environ.get("TRADING_LAB_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TRADING_LAB_TEST_DATABASE_URL to a dedicated PostgreSQL test database")
    engine = create_engine(url, connect_args={"options": "-c timezone=UTC"}, hide_parameters=True)
    schema = f"trading_lab_test_{uuid4().hex}"
    created = False
    try:
        if engine.dialect.name != "postgresql":
            raise ValueError("Integration tests require PostgreSQL")
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        isolated = engine.execution_options(schema_translate_map={None: schema})
        Base.metadata.create_all(isolated)
        yield build_session_factory(isolated)
    finally:
        try:
            if created:
                with engine.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            engine.dispose()


@pytest.mark.integration
def test_postgres_candle_repeat_and_correction(postgres_factory, spot, candle):
    with transaction(postgres_factory) as session:
        repo = PostgresMarketDataRepository(session)
        repo.save_market(spot)
        assert repo.upsert_candles(spot, "1h", [candle]) == WriteCounts(1, 0)
    with transaction(postgres_factory) as session:
        repo = PostgresMarketDataRepository(session)
        assert repo.upsert_candles(spot, "1h", [candle]) == WriteCounts(0, 0)
        corrected = replace(candle, close=Decimal("106"))
        assert repo.upsert_candles(spot, "1h", [corrected]) == WriteCounts(0, 1)
        assert list(repo.iter_candles(spot, "1h", start=START, end=END)) == [corrected]


@pytest.mark.integration
def test_postgres_funding_null_mark_price_and_rollback(postgres_factory, perpetual):
    rate = FundingRate(START, Decimal("-0.0001"), "binance")
    with transaction(postgres_factory) as session:
        repo = PostgresMarketDataRepository(session)
        repo.save_market(perpetual)
        assert repo.upsert_funding_rates(perpetual, [rate]) == WriteCounts(1, 0)
    with transaction(postgres_factory) as session:
        repo = PostgresMarketDataRepository(session)
        assert repo.upsert_funding_rates(perpetual, [rate]) == WriteCounts(0, 0)
    with pytest.raises(RuntimeError, match="Deliberate rollback"):
        with transaction(postgres_factory) as session:
            repo = PostgresMarketDataRepository(session)
            assert repo.upsert_funding_rates(
                perpetual, [replace(rate, mark_price=Decimal("100"))]
            ) == WriteCounts(0, 1)
            raise RuntimeError("Deliberate rollback")
    with transaction(postgres_factory) as session:
        repo = PostgresMarketDataRepository(session)
        assert list(repo.iter_funding_rates(perpetual, start=START, end=END)) == [rate]
