"""Offline sync persistence tests; SQL is compiled, not executed on PostgreSQL."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from trading_lab.domain.enums import MarketType
from trading_lab.domain.exceptions import DataCoverageError, InvalidMarketDataError, RepositoryError
from trading_lab.domain.models import Market
from trading_lab.domain.sync import CandleCoverage, SyncDataset, SyncJob, SyncStatus
from trading_lab.domain.timeframes import CandleRange
from trading_lab.infrastructure.database.sync_repository import PostgresSyncRepository

START = datetime(2026, 10, 31, tzinfo=UTC)
HOUR = timedelta(hours=1)


@pytest.fixture
def job():
    market = Market("binance", MarketType.SPOT, "BTC/USDT", "BTCUSDT", "BTC", "USDT")
    return SyncJob(
        market,
        SyncDataset.CANDLES,
        START,
        START + 5 * HOUR,
        started_at=START + 6 * HOUR,
        timeframe="1h",
    )


@pytest.fixture
def session():
    return MagicMock(spec=Session)


def result(*, scalar=None, row=None):
    value = MagicMock()
    value.scalar_one_or_none.return_value = scalar
    value.mappings.return_value.one_or_none.return_value = row
    return value


def compile_query(statement):
    return statement.compile(dialect=postgresql.dialect())


def assert_transaction_untouched(session):
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.close.assert_not_called()


def test_job_creation_and_read_roundtrip_with_json_details(session, job):
    write_result = result()
    session.execute.side_effect = [result(scalar=1), write_result]
    repo = PostgresSyncRepository(session)
    repo.create_job(job, details={"warnings": ["Test warning"]})
    payload = compile_query(session.execute.call_args.args[0]).params
    assert payload["status"] == "pending"
    assert payload["last_committed_time"] is None
    assert payload["details"] == {"warnings": ["Test warning"]}
    write_result.close.assert_called_once()
    row = {
        **payload,
        "exchange": "binance",
        "market_type": MarketType.SPOT,
        "symbol_unified": "BTC/USDT",
        "symbol_native": "BTCUSDT",
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "settle_asset": None,
        "contract_size": None,
    }
    session.execute.side_effect = None
    session.execute.return_value = result(row=row)
    assert repo.get_job(job.id) == job
    assert "JOIN markets" in str(compile_query(session.execute.call_args.args[0]))
    assert_transaction_untouched(session)


def test_non_pending_job_cannot_be_created(session, job):
    with pytest.raises(ValueError):
        PostgresSyncRepository(session).create_job(replace(job, status=SyncStatus.RUNNING))
    session.execute.assert_not_called()


@pytest.mark.parametrize("invalid", [float("nan"), Decimal("0.1"), START])
def test_non_json_details_fail_before_database_access(session, job, invalid):
    with pytest.raises(ValueError):
        PostgresSyncRepository(session).create_job(job, details={"invalid": invalid})
    session.execute.assert_not_called()


def test_update_matches_prior_snapshot_and_preserves_omitted_details(session, job):
    session.execute.side_effect = [result(scalar=1), result(scalar=job.id)]
    PostgresSyncRepository(session).update_job(
        replace(job, status=SyncStatus.RUNNING), previous=job
    )
    compiled = compile_query(session.execute.call_args.args[0])
    sql = str(compiled)
    assert "IS NOT DISTINCT FROM" in sql
    assert "last_committed_time IS NOT DISTINCT FROM NULL" in sql
    assert "details" not in compiled.params
    assert_transaction_untouched(session)


def test_stale_update_raises_without_replaying_or_committing(session, job):
    session.execute.side_effect = [result(scalar=1), result()]
    with pytest.raises(RepositoryError, match="reload"):
        PostgresSyncRepository(session).update_job(
            replace(job, status=SyncStatus.RUNNING), previous=job
        )
    assert session.execute.call_count == 2
    assert_transaction_untouched(session)


@pytest.mark.parametrize("change", ["identity", "counter", "cursor", "terminal"])
def test_invalid_state_rewrites_fail_before_sql(session, job, change):
    previous = replace(
        job, status=SyncStatus.RUNNING, inserted_count=2, last_committed_time=START + HOUR
    )
    if change == "identity":
        updated = replace(previous, requested_end=previous.requested_end + HOUR)
    elif change == "counter":
        updated = replace(previous, inserted_count=1)
    elif change == "cursor":
        updated = replace(previous, last_committed_time=START)
    else:
        previous = replace(
            previous, status=SyncStatus.SUCCEEDED, finished_at=previous.started_at + HOUR
        )
        updated = previous
    with pytest.raises(ValueError):
        PostgresSyncRepository(session).update_job(updated, previous=previous)
    session.execute.assert_not_called()


def test_failure_record_keeps_progress_and_replaces_details_explicitly(session, job):
    previous = replace(
        job, status=SyncStatus.RUNNING, inserted_count=2, last_committed_time=START + HOUR
    )
    failed = replace(
        previous,
        status=SyncStatus.FAILED,
        error="Provider timed out",
        finished_at=previous.started_at + HOUR,
    )
    session.execute.side_effect = [result(scalar=1), result(scalar=job.id)]
    PostgresSyncRepository(session).update_job(
        failed, previous=previous, details={"warnings": ["Coverage incomplete"]}
    )
    payload = compile_query(session.execute.call_args.args[0]).params
    assert payload["inserted_count"] == 2
    assert payload["last_committed_time"] == START + HOUR
    assert payload["status"] == "failed"
    assert payload["details"] == {"warnings": ["Coverage incomplete"]}


@pytest.mark.parametrize("written", [True, False])
def test_coverage_roundtrip_and_newer_snapshot_guard(session, job, written):
    requested = CandleRange(job.requested_start, job.requested_end, "1h")
    coverage = CandleCoverage.inspect(
        job.market,
        requested,
        iter([START + HOUR]),
        checked_at=job.started_at,
        warnings=("Test warning",),
    )
    session.execute.side_effect = [result(scalar=1), result(scalar=1 if written else None)]
    repo = PostgresSyncRepository(session)
    assert repo.save_coverage(coverage) is written
    compiled = compile_query(session.execute.call_args.args[0])
    assert "excluded.checked_at > data_coverage.checked_at" in str(compiled)
    payload = compiled.params
    assert payload["missing_ranges"] == [
        {"start": START.isoformat(), "end": (START + HOUR).isoformat()},
        {"start": (START + 2 * HOUR).isoformat(), "end": (START + 5 * HOUR).isoformat()},
    ]
    session.execute.side_effect = [result(scalar=1), result(row=payload)]
    assert repo.get_coverage(job.market, "1h") == coverage
    assert_transaction_untouched(session)


def test_missing_job_and_coverage_return_none_without_fabricating_status(session, job):
    session.execute.return_value = result()
    repo = PostgresSyncRepository(session)
    assert repo.get_job(job.id) is None
    assert repo.get_job_details(job.id) is None
    session.execute.side_effect = [result(scalar=1), result()]
    assert repo.get_coverage(job.market, "1h") is None


def test_details_are_detached_from_db_result(session, job):
    stored = {"warnings": ["Original"]}
    session.execute.return_value = result(scalar=stored)
    loaded = PostgresSyncRepository(session).get_job_details(job.id)
    loaded["warnings"].append("Local edit")
    assert stored == {"warnings": ["Original"]}


def test_corrupt_coverage_json_is_rejected(session, job):
    requested = CandleRange(job.requested_start, job.requested_end, "1h")
    coverage = CandleCoverage.inspect(job.market, requested, iter(()), checked_at=job.started_at)
    session.execute.side_effect = [result(scalar=1), result(scalar=1)]
    repo = PostgresSyncRepository(session)
    repo.save_coverage(coverage)
    row = compile_query(session.execute.call_args.args[0]).params
    row["warnings"] = "Invalid JSON shape"
    session.execute.side_effect = [result(scalar=1), result(row=row)]
    with pytest.raises(InvalidMarketDataError):
        repo.get_coverage(job.market, "1h")


def test_missing_market_does_not_create_orphan_job(session, job):
    session.execute.return_value = result()
    with pytest.raises(DataCoverageError):
        PostgresSyncRepository(session).create_job(job)
    assert session.execute.call_count == 1


def test_db_failure_is_chained_and_transaction_remains_callers_responsibility(session, job):
    failure = DBAPIError("SELECT ...", {}, RuntimeError("Private database details"))
    session.execute.side_effect = failure
    with pytest.raises(RepositoryError) as captured:
        PostgresSyncRepository(session).create_job(job)
    assert captured.value.__cause__ is failure
    assert "Private database details" not in str(captured.value)
    assert_transaction_untouched(session)
