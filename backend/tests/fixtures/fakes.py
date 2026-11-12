"""Small transactional in-memory adapters exclusively for offline tests/demo."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field

from trading_lab.application.ports import DataUnit
from trading_lab.domain.enums import MarketType
from trading_lab.domain.exceptions import RepositoryError, TransientProviderError
from trading_lab.domain.interfaces import WriteCounts


@dataclass
class MemoryState:
    markets: dict = field(default_factory=dict)
    candles: dict = field(default_factory=dict)
    funding: dict = field(default_factory=dict)
    jobs: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)
    in_transaction: bool = False


class MemoryData:
    def __init__(self, state):
        self.state = state

    def save_market(self, market):
        self.state.markets[(market.exchange, market.market_type, market.symbol)] = market

    def find_market(self, exchange, market_type, symbol):
        return self.state.markets.get((exchange, market_type, symbol))

    def iter_candles(self, market, timeframe, *, start, end):
        return iter(
            sorted(
                (
                    bar
                    for (saved, tf, timestamp), bar in self.state.candles.items()
                    if saved == market and tf == timeframe and start <= timestamp < end
                ),
                key=lambda bar: bar.open_time,
            )
        )

    def iter_candle_times(self, market, timeframe, *, start, end):
        return (bar.open_time for bar in self.iter_candles(market, timeframe, start=start, end=end))

    def latest_candle_time(self, market, timeframe, *, before):
        return max(
            (
                timestamp
                for saved, tf, timestamp in self.state.candles
                if saved == market and tf == timeframe and timestamp < before
            ),
            default=None,
        )

    def latest_funding_time(self, market, *, before):
        return max(
            (
                timestamp
                for saved, timestamp in self.state.funding
                if saved == market and timestamp < before
            ),
            default=None,
        )

    def iter_funding_rates(self, market, *, start, end):
        return iter(
            sorted(
                (
                    event
                    for (saved, timestamp), event in self.state.funding.items()
                    if saved == market and start <= timestamp < end
                ),
                key=lambda event: event.funding_time,
            )
        )

    @staticmethod
    def _write(storage, entries):
        inserted = updated = 0
        for key, value in entries:
            if key not in storage:
                inserted += 1
            elif storage[key] != value:
                updated += 1
            storage[key] = value
        return WriteCounts(inserted, updated)

    def upsert_candles(self, market, timeframe, candles):
        return self._write(
            self.state.candles, (((market, timeframe, bar.open_time), bar) for bar in candles)
        )

    def upsert_funding_rates(self, market, rates):
        return self._write(
            self.state.funding, (((market, event.funding_time), event) for event in rates)
        )


class MemorySync:
    def __init__(self, state):
        self.state = state

    def create_job(self, job, *, details=None):
        self.state.jobs[job.id] = job
        self.state.details[job.id] = details or {}

    def update_job(self, job, *, previous, details=None):
        if self.state.jobs.get(job.id) != previous:
            raise RepositoryError("Stale fake snapshot")
        self.state.jobs[job.id] = job
        if details is not None:
            self.state.details[job.id] = details

    def get_job(self, job_id):
        return self.state.jobs.get(job_id)

    def save_coverage(self, coverage):
        self.state.coverage[(coverage.market, coverage.requested.timeframe)] = coverage
        return True

    def get_coverage(self, market, timeframe):
        return self.state.coverage.get((market, timeframe))


def memory_units(state):
    @contextmanager
    def unit():
        staged = deepcopy(state)
        state.in_transaction = True
        try:
            yield DataUnit(MemoryData(staged), MemorySync(staged))
        except BaseException:
            raise
        else:
            for key in ("markets", "candles", "funding", "jobs", "details", "coverage"):
                setattr(state, key, getattr(staged, key))
        finally:
            state.in_transaction = False

    return unit


class FakeProvider:
    def __init__(self, state, market, candles=(), funding=(), fail_on=None):
        self.state, self.market, self.candles, self.funding = state, market, candles, funding
        self.market_type, self.exchange = market.market_type, market.exchange
        self.supports_funding_history = market.market_type is MarketType.PERPETUAL
        self.fail_on, self.calls = fail_on, []

    def get_market(self, symbol):
        assert symbol == self.market.symbol
        return self.market

    def get_timeframes(self):
        return frozenset({"1h"})

    def _page(self, records, key, start, end, limit):
        assert not self.state.in_transaction, "Network work must be outside the transaction"
        self.calls.append((start, end))
        if self.fail_on == len(self.calls):
            raise TransientProviderError("Synthetic page failure")
        return [item for item in records if start <= key(item) < end][:limit]

    def fetch_candles(self, market, timeframe, *, start, end, limit):
        return self._page(self.candles, lambda bar: bar.open_time, start, end, limit)

    def fetch_funding_rates(self, market, *, start, end, limit):
        return self._page(self.funding, lambda event: event.funding_time, start, end, limit)


class MemoryRuns:
    def __init__(self):
        self.records = {}

    def begin(self, run_id, *args):
        self.records[run_id] = {"status": "running"}

    def complete(self, result):
        self.records[result.run_id].update(status="completed", result=result)

    def fail(self, run_id, error):
        self.records[run_id].update(status="failed", error=error)

    def report_status(self, run_id, *, path=None, error=None):
        self.records[run_id].update(report_path=path, report_error=error)
