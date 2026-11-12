"""Offline consistency checks for sync progress and observed candle coverage."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_lab.domain.enums import MarketType
from trading_lab.domain.exceptions import InvalidMarketDataError
from trading_lab.domain.models import Market
from trading_lab.domain.sync import CandleCoverage, SyncDataset, SyncJob, SyncStatus
from trading_lab.domain.timeframes import CandleRange

START = datetime(2026, 10, 31, tzinfo=UTC)
HOUR = timedelta(hours=1)
CHECKED_AT = START + 8 * HOUR


@pytest.fixture
def spot():
    return Market("binance", MarketType.SPOT, "BTC/USDT", "BTCUSDT", "BTC", "USDT")


@pytest.fixture
def job(spot):
    return SyncJob(
        spot, SyncDataset.CANDLES, START, START + 5 * HOUR, started_at=CHECKED_AT, timeframe="1h"
    )


@pytest.fixture
def coverage(spot):
    return CandleCoverage.inspect(
        spot,
        CandleRange(START, START + 5 * HOUR, "1h"),
        (START + index * HOUR for index in (1, 3)),
        checked_at=CHECKED_AT,
    )


def test_failed_job_preserves_prior_committed_progress(job):
    running = replace(
        job,
        status=SyncStatus.RUNNING,
        last_committed_time=START + HOUR,
        inserted_count=2,
        updated_count=1,
    )
    failed = replace(
        running,
        status=SyncStatus.FAILED,
        error="Synthetic provider failure",
        finished_at=CHECKED_AT + HOUR,
    )
    assert failed.id == job.id
    assert failed.last_committed_time == START + HOUR
    assert (failed.inserted_count, failed.updated_count) == (2, 1)
    assert job.status is SyncStatus.PENDING
    assert job.inserted_count == 0


def test_unchanged_page_can_confirm_progress_without_claiming_writes(job):
    running = replace(job, status=SyncStatus.RUNNING, last_committed_time=START)
    assert running.inserted_count == running.updated_count == 0


@pytest.mark.parametrize("status", [SyncStatus.SUCCEEDED, SyncStatus.PARTIAL, SyncStatus.FAILED])
def test_terminal_status_requires_finish_time(job, status):
    with pytest.raises(ValueError):
        replace(job, status=status, error="Failure" if status is SyncStatus.FAILED else None)


@pytest.mark.parametrize(
    "changes",
    [
        {"requested_end": START},
        {"requested_start": START + timedelta(minutes=1)},
        {"started_at": CHECKED_AT.replace(tzinfo=None)},
        {"inserted_count": -1},
        {"updated_count": True},
        {"status": SyncStatus.RUNNING, "inserted_count": 1},
        {"last_committed_time": START},
        {"status": SyncStatus.RUNNING, "last_committed_time": START - HOUR},
        {"status": SyncStatus.RUNNING, "last_committed_time": START + 5 * HOUR},
        {"status": SyncStatus.RUNNING, "last_committed_time": START + timedelta(minutes=1)},
        {"status": SyncStatus.RUNNING, "finished_at": CHECKED_AT},
        {"status": SyncStatus.SUCCEEDED, "finished_at": CHECKED_AT - HOUR},
        {"status": SyncStatus.SUCCEEDED, "finished_at": CHECKED_AT, "error": "Failure"},
        {"status": SyncStatus.FAILED, "finished_at": CHECKED_AT},
        {"status": SyncStatus.FAILED, "finished_at": CHECKED_AT, "error": " "},
        {"status": "running"},
    ],
)
def test_inconsistent_job_records_are_rejected(job, changes):
    with pytest.raises((TypeError, ValueError)):
        replace(job, **changes)


def test_funding_jobs_use_event_times_instead_of_candle_boundaries(spot):
    perpetual = Market(
        "binance",
        MarketType.PERPETUAL,
        "BTC/USDT:USDT",
        "BTCUSDT",
        "BTC",
        "USDT",
        settle_asset="USDT",
        contract_size=Decimal("1"),
    )
    event_time = START + timedelta(minutes=17)
    funding = SyncJob(
        perpetual,
        SyncDataset.FUNDING_RATES,
        START,
        START + HOUR,
        started_at=CHECKED_AT,
        status=SyncStatus.RUNNING,
        last_committed_time=event_time,
    )
    assert funding.timeframe is None
    assert funding.last_committed_time == event_time
    with pytest.raises(ValueError):
        replace(funding, market=spot)
    with pytest.raises(ValueError):
        replace(funding, timeframe="1h")


def test_sync_times_are_normalized_without_changing_their_instant(job):
    offset = timezone(timedelta(hours=2))
    converted = replace(
        job,
        requested_start=START.astimezone(offset),
        requested_end=job.requested_end.astimezone(offset),
        started_at=CHECKED_AT.astimezone(offset),
    )
    assert converted == job
    assert converted.requested_start.tzinfo is UTC


def test_coverage_reports_leading_internal_and_trailing_gaps(coverage):
    assert coverage.candle_count == 2
    assert coverage.missing_bar_count == 3
    assert coverage.complete is False
    assert coverage.first_open_time == START + HOUR
    assert coverage.last_open_time == START + 3 * HOUR
    assert coverage.missing_ranges == tuple(
        CandleRange(START + begin * HOUR, START + end * HOUR, "1h")
        for begin, end in ((0, 1), (2, 3), (4, 5))
    )


def test_empty_coverage_remains_missing_instead_of_becoming_zero_price_data(spot):
    requested = CandleRange(START, START + HOUR, "1h")
    result = CandleCoverage.inspect(
        spot,
        requested,
        iter(()),
        checked_at=CHECKED_AT,
        warnings=("Historical availability not established",),
    )
    assert result.candle_count == 0
    assert result.first_open_time is result.last_open_time is None
    assert result.missing_ranges == (requested,)
    assert result.complete is False
    assert result.warnings == ("Historical availability not established",)


def test_full_coverage_consumes_input_once_and_reports_exact_endpoints(spot):
    requested = CandleRange(START, START + 3 * HOUR, "1h")
    observations = (START + index * HOUR for index in range(3))
    result = CandleCoverage.inspect(spot, requested, observations, checked_at=CHECKED_AT)
    assert result.complete is True
    assert result.candle_count == 3
    assert result.missing_ranges == ()
    assert (result.first_open_time, result.last_open_time) == (START, START + 2 * HOUR)
    assert list(observations) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"candle_count": 3},
        {"candle_count": -1},
        {"first_open_time": START},
        {"last_open_time": START + 4 * HOUR},
        {"checked_at": CHECKED_AT.replace(tzinfo=None)},
        {"missing_ranges": ()},
        {
            "missing_ranges": (
                CandleRange(START, START + 2 * HOUR, "1h"),
                CandleRange(START + HOUR, START + 3 * HOUR, "1h"),
            )
        },
        {"missing_ranges": (CandleRange(START - HOUR, START, "1h"),)},
        {"missing_ranges": (CandleRange(START, START + HOUR, "15m"),)},
        {"warnings": ("",)},
    ],
)
def test_inconsistent_coverage_summaries_are_rejected(coverage, changes):
    with pytest.raises((TypeError, ValueError)):
        replace(coverage, **changes)


def test_inspection_validates_all_observations_even_after_a_leading_gap(spot):
    requested = CandleRange(START, START + 5 * HOUR, "1h")
    with pytest.raises(InvalidMarketDataError):
        CandleCoverage.inspect(
            spot, requested, iter([START + HOUR, START + HOUR]), checked_at=CHECKED_AT
        )


def test_highest_confirmed_timestamp_does_not_imply_complete_coverage(job, coverage):
    completed = replace(
        job,
        status=SyncStatus.SUCCEEDED,
        last_committed_time=START + 4 * HOUR,
        finished_at=CHECKED_AT + HOUR,
    )
    assert completed.status is SyncStatus.SUCCEEDED
    assert coverage.complete is False


def test_progress_and_coverage_records_cannot_be_mutated(job, coverage):
    with pytest.raises(FrozenInstanceError):
        job.inserted_count = 100
    with pytest.raises(FrozenInstanceError):
        coverage.candle_count = 5
