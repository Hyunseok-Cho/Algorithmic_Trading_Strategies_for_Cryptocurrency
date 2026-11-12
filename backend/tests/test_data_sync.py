from dataclasses import replace
from decimal import Decimal

import pytest

from tests.fixtures.fakes import FakeProvider, MemoryState, memory_units
from tests.fixtures.scenarios import HOUR, START, bars, market
from trading_lab.application.market_data_service import MarketDataService
from trading_lab.domain.exceptions import TransientProviderError
from trading_lab.domain.models import FundingRate
from trading_lab.domain.sync import SyncStatus
from trading_lab.domain.timeframes import CandleRange


def setup_sync(prices=(100, 101, 102, 103), *, cutoff=None):
    state = MemoryState()
    saved_market = market()
    candles = bars(prices)
    provider = FakeProvider(state, saved_market, candles)
    service = MarketDataService(
        memory_units(state), clock=lambda: cutoff or START + len(candles) * HOUR
    )
    return state, saved_market, candles, provider, service


def test_first_sync_repeat_increment_and_gap_repair():
    state, saved_market, candles, provider, service = setup_sync()
    requested = CandleRange(START, START + 4 * HOUR, "1h")
    first = service.sync_candles(provider, saved_market.symbol, requested, limit=2)
    assert first.inserted_count == 4 and first.status == "succeeded"
    assert len(provider.calls) == 2
    second = service.sync_candles(provider, saved_market.symbol, requested, limit=2)
    assert second.inserted_count == second.updated_count == 0
    assert len(provider.calls) == 2
    del state.candles[(saved_market, "1h", START + HOUR)]
    repaired = service.sync_candles(provider, saved_market.symbol, requested)
    assert repaired.inserted_count == 1
    assert provider.calls[-1] == (START + HOUR, START + 2 * HOUR)
    provider.candles = candles + bars([104], start=START + 4 * HOUR)
    service = MarketDataService(memory_units(state), clock=lambda: START + 5 * HOUR)
    incremental = service.sync_candles(
        provider, saved_market.symbol, CandleRange(START, START + 5 * HOUR, "1h")
    )
    assert incremental.inserted_count == 1
    assert provider.calls[-1][0] == START + 4 * HOUR


def test_refresh_corrects_a_saved_candle_without_duplicates():
    state, saved_market, candles, provider, service = setup_sync()
    requested = CandleRange(START, START + 4 * HOUR, "1h")
    service.sync_candles(provider, saved_market.symbol, requested)
    provider.candles = (replace(candles[0], close=Decimal("100.5")), *candles[1:])
    updated = service.sync_candles(provider, saved_market.symbol, requested, refresh=True)
    assert updated.inserted_count == 0 and updated.updated_count == 1
    assert len(state.candles) == 4


def test_open_candle_is_not_saved_and_status_is_db_only():
    state, saved_market, _, provider, service = setup_sync(cutoff=START + 3 * HOUR + HOUR / 2)
    service.sync_candles(provider, saved_market.symbol, CandleRange(START, START + 4 * HOUR, "1h"))
    assert len(state.candles) == 3
    calls = len(provider.calls)
    status = service.status(
        "binance",
        saved_market.market_type,
        saved_market.symbol,
        CandleRange(START, START + 3 * HOUR, "1h"),
    )
    assert status["complete"]
    assert len(provider.calls) == calls


def test_empty_or_later_listing_history_remains_a_reported_gap():
    state, saved_market, candles, provider, service = setup_sync()
    provider.candles = candles[2:]
    result = service.sync_candles(
        provider, saved_market.symbol, CandleRange(START, START + 4 * HOUR, "1h")
    )
    assert result.status == "partial" and result.candle_count == 2
    assert result.missing_ranges[0]["start"] == START.isoformat()
    assert state.jobs[result.job_id].status is SyncStatus.PARTIAL


def test_mid_sync_failure_preserves_first_page_and_can_resume():
    state, saved_market, candles, provider, service = setup_sync()
    provider.fail_on = 2
    requested = CandleRange(START, START + 4 * HOUR, "1h")
    with pytest.raises(TransientProviderError):
        service.sync_candles(provider, saved_market.symbol, requested, limit=2)
    assert len(state.candles) == 2
    failed = next(iter(state.jobs.values()))
    assert failed.status is SyncStatus.FAILED
    assert failed.inserted_count == 2
    resumed_provider = FakeProvider(state, saved_market, candles)
    result = service.sync_candles(resumed_provider, saved_market.symbol, requested)
    assert result.inserted_count == 2
    assert resumed_provider.calls[0][0] == START + 2 * HOUR


def test_no_completed_range_does_not_create_a_job():
    state, saved_market, _, provider, service = setup_sync(cutoff=START)
    result = service.sync_candles(
        provider, saved_market.symbol, CandleRange(START, START + HOUR, "1h")
    )
    assert result.status == "no_complete_candles"
    assert not state.jobs and not state.candles and not provider.calls


def test_page_and_cursor_roll_back_together_on_cursor_write_failure():
    from contextlib import contextmanager

    from trading_lab.application.ports import DataUnit

    state, saved_market, _, provider, _ = setup_sync()
    units = memory_units(state)

    class FailProgress:
        def __init__(self, target):
            self.target = target

        def __getattr__(self, name):
            return getattr(self.target, name)

        def update_job(self, job, *, previous, details=None):
            if job.inserted_count:
                raise RuntimeError("Synthetic cursor write failure")
            self.target.update_job(job, previous=previous, details=details)

    @contextmanager
    def failing_units():
        with units() as unit:
            yield DataUnit(unit.data, FailProgress(unit.sync))

    service = MarketDataService(failing_units, clock=lambda: START + 4 * HOUR)
    with pytest.raises(RuntimeError, match="cursor"):
        service.sync_candles(
            provider, saved_market.symbol, CandleRange(START, START + 4 * HOUR, "1h")
        )
    assert not state.candles
    failed = next(iter(state.jobs.values()))
    assert failed.status is SyncStatus.FAILED
    assert failed.last_committed_time is None
    assert failed.inserted_count == 0


def test_funding_increment_and_refresh_do_not_infer_a_fixed_schedule():
    state = MemoryState()
    saved_market = market(True)
    events = (
        FundingRate(START + HOUR / 2, Decimal("0.01"), "fixture"),
        FundingRate(START + 2 * HOUR, Decimal("-0.01"), "fixture"),
    )
    provider = FakeProvider(state, saved_market, funding=events)
    service = MarketDataService(memory_units(state), clock=lambda: START + 4 * HOUR)
    result = service.sync_funding(provider, saved_market.symbol, START, START + 4 * HOUR, limit=1)
    assert result.inserted_count == 2 and result.warnings
    assert state.details[result.job_id]["funding_schedule_verified"] is False
    repeat = service.sync_funding(provider, saved_market.symbol, START, START + 4 * HOUR)
    assert repeat.inserted_count == 0
    provider.funding = (replace(events[0], rate=Decimal("0.02")), events[1])
    corrected = service.sync_funding(
        provider, saved_market.symbol, START, START + 4 * HOUR, refresh=True
    )
    assert corrected.updated_count == 1
