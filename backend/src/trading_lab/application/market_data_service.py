"""Explicit data synchronization; network calls never hold DB transactions open."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from trading_lab.application.dto import SyncResult
from trading_lab.domain.enums import MarketType
from trading_lab.domain.exceptions import DataCoverageError, InvalidMarketDataError
from trading_lab.domain.interfaces import MarketDataProvider
from trading_lab.domain.sync import CandleCoverage, SyncDataset, SyncJob, SyncStatus
from trading_lab.domain.timeframes import CandleRange, find_candle_gaps, timeframe_delta


class MarketDataService:
    def __init__(self, unit_factory, *, clock=lambda: datetime.now(UTC)):
        self._unit = unit_factory
        self._clock = clock

    def _coverage(self, market, requested, *, persist=False):
        with self._unit() as unit:
            coverage = CandleCoverage.inspect(
                market,
                requested,
                unit.data.iter_candle_times(
                    market, requested.timeframe, start=requested.start, end=requested.end
                ),
                checked_at=self._clock(),
                warnings=("Missing ranges are not proof that exchange history exists there",),
            )
            if persist:
                unit.sync.save_coverage(coverage)
            return coverage

    def status(self, exchange, market_type, symbol, requested: CandleRange):
        with self._unit() as unit:
            market = unit.data.find_market(exchange, market_type, symbol)
        if market is None:
            raise DataCoverageError("Market is not stored locally; run data sync first")
        coverage = self._coverage(market, requested)
        return {
            "exchange": exchange,
            "market_type": market_type.value,
            "symbol": symbol,
            "timeframe": requested.timeframe,
            "start": requested.start.isoformat(),
            "end": requested.end.isoformat(),
            "complete": coverage.complete,
            "candle_count": coverage.candle_count,
            "missing_bar_count": coverage.missing_bar_count,
            "missing_ranges": self._gaps(coverage),
            "warnings": coverage.warnings,
        }

    @staticmethod
    def _gaps(coverage):
        return tuple(
            {"start": gap.start.isoformat(), "end": gap.end.isoformat()}
            for gap in coverage.missing_ranges
        )

    def _start(self, provider, symbol, dataset, start, end, timeframe):
        market = provider.get_market(symbol)
        job = SyncJob(market, dataset, start, end, self._clock(), timeframe=timeframe)
        with self._unit() as unit:
            unit.data.save_market(market)
            unit.sync.create_job(job)
        running = replace(job, status=SyncStatus.RUNNING)
        try:
            with self._unit() as unit:
                unit.sync.update_job(running, previous=job)
        except (Exception, KeyboardInterrupt) as exc:
            self._fail(job, exc)
            raise
        return running

    def _fail(self, job, failure):
        try:
            # Reload after rollback: a prior page may have committed successfully.
            with self._unit() as unit:
                current = unit.sync.get_job(job.id)
                if current is not None and current.status in (
                    SyncStatus.PENDING,
                    SyncStatus.RUNNING,
                ):
                    failed = replace(
                        current,
                        status=SyncStatus.FAILED,
                        finished_at=self._clock(),
                        error=f"{type(failure).__name__}: sync interrupted; inspect CLI output",
                    )
                    unit.sync.update_job(failed, previous=current)
        except Exception:
            failure.add_note("Could not persist failure status; last committed pages remain in DB")

    def sync_candles(
        self,
        provider: MarketDataProvider,
        symbol: str,
        requested: CandleRange,
        *,
        limit=500,
        refresh=False,
    ) -> SyncResult:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Page limit must be in [1, 1000]")
        cutoff = self._clock()
        completed = requested.completed_before(cutoff)
        if completed is None:
            return SyncResult(
                job_id=None,
                status="no_complete_candles",
                warnings=("No complete requested candle exists at the captured clock",),
            )
        if requested.timeframe not in provider.get_timeframes():
            from trading_lab.domain.exceptions import UnsupportedTimeframeError

            raise UnsupportedTimeframeError("Provider does not support the requested timeframe")
        job = self._start(
            provider,
            symbol,
            SyncDataset.CANDLES,
            completed.start,
            completed.end,
            completed.timeframe,
        )
        try:
            existing = self._coverage(job.market, completed)
            ranges = (completed,) if refresh else existing.missing_ranges
            interval = timeframe_delta(completed.timeframe)
            for gap in ranges:
                cursor = gap.start
                while cursor < gap.end:
                    page = list(
                        provider.fetch_candles(
                            job.market, gap.timeframe, start=cursor, end=gap.end, limit=limit
                        )
                    )
                    page = [
                        bar
                        for bar in page
                        if cursor <= bar.open_time < gap.end and bar.open_time + interval <= cutoff
                    ]
                    if not page:
                        break  # Leave unavailable/empty history as a reported gap.
                    list(
                        find_candle_gaps(
                            CandleRange(cursor, gap.end, gap.timeframe),
                            (bar.open_time for bar in page),
                        )
                    )
                    last = page[-1].open_time
                    if last < cursor:
                        raise InvalidMarketDataError("Candle pagination did not advance")
                    with self._unit() as unit:
                        counts = unit.data.upsert_candles(job.market, gap.timeframe, page)
                        confirmed = max(last, job.last_committed_time or last)
                        updated = replace(
                            job,
                            last_committed_time=confirmed,
                            inserted_count=job.inserted_count + counts.inserted,
                            updated_count=job.updated_count + counts.updated,
                        )
                        unit.sync.update_job(updated, previous=job)
                    job = updated  # Advance only AFTER a successful commit.
                    cursor = last + interval
            coverage = self._coverage(job.market, completed, persist=True)
            finished = replace(
                job,
                status=SyncStatus.SUCCEEDED if coverage.complete else SyncStatus.PARTIAL,
                finished_at=self._clock(),
            )
            with self._unit() as unit:
                unit.sync.update_job(
                    finished,
                    previous=job,
                    details={
                        "missing_ranges": list(self._gaps(coverage)),
                        "warnings": list(coverage.warnings),
                        "captured_cutoff": cutoff.isoformat(),
                        "complete": coverage.complete,
                    },
                )
            return SyncResult(
                job_id=job.id,
                status=finished.status.value,
                inserted_count=job.inserted_count,
                updated_count=job.updated_count,
                candle_count=coverage.candle_count,
                missing_ranges=self._gaps(coverage),
                warnings=coverage.warnings,
            )
        except (Exception, KeyboardInterrupt) as exc:
            self._fail(job, exc)
            raise

    def sync_funding(
        self,
        provider: MarketDataProvider,
        symbol: str,
        start: datetime,
        end: datetime,
        *,
        limit=500,
        refresh=False,
    ) -> SyncResult:
        if provider.market_type is not MarketType.PERPETUAL:
            raise ValueError("Funding sync requires a perpetual market")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Page limit must be in [1, 1000]")
        cutoff = self._clock().astimezone(UTC)
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("Funding range requires timezone-aware timestamps")
        start, end = start.astimezone(UTC), min(end.astimezone(UTC), cutoff)
        end = end.replace(microsecond=(end.microsecond // 1000) * 1000)
        if start >= end:
            raise ValueError("No elapsed funding range to synchronize")
        job = self._start(provider, symbol, SyncDataset.FUNDING_RATES, start, end, None)
        try:
            with self._unit() as unit:
                latest = unit.data.latest_funding_time(job.market, before=end)
            cursor = (
                start
                if refresh or latest is None
                else max(start, latest + timedelta(milliseconds=1))
            )
            while cursor < end:
                page = list(
                    provider.fetch_funding_rates(job.market, start=cursor, end=end, limit=limit)
                )
                if not page:
                    break
                times = [rate.funding_time for rate in page]
                if times != sorted(set(times)) or any(not cursor <= value < end for value in times):
                    raise InvalidMarketDataError("Funding pagination returned invalid timestamps")
                last = times[-1]
                with self._unit() as unit:
                    counts = unit.data.upsert_funding_rates(job.market, page)
                    updated = replace(
                        job,
                        last_committed_time=max(last, job.last_committed_time or last),
                        inserted_count=job.inserted_count + counts.inserted,
                        updated_count=job.updated_count + counts.updated,
                    )
                    unit.sync.update_job(updated, previous=job)
                job = updated
                cursor = last + timedelta(milliseconds=1)
            warnings = (
                "Funding event schedule completeness is not inferred from a fixed interval; "
                "use --refresh to recheck earlier events and an audited schedule for strict backtests",
            )
            finished = replace(job, status=SyncStatus.SUCCEEDED, finished_at=self._clock())
            with self._unit() as unit:
                unit.sync.update_job(
                    finished,
                    previous=job,
                    details={"warnings": list(warnings), "funding_schedule_verified": False},
                )
            return SyncResult(
                job_id=job.id,
                status=finished.status.value,
                inserted_count=job.inserted_count,
                updated_count=job.updated_count,
                warnings=warnings,
            )
        except (Exception, KeyboardInterrupt) as exc:
            self._fail(job, exc)
            raise
