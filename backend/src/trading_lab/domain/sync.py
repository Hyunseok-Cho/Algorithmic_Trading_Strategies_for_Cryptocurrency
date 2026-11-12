"""Immutable sync-job and candle-coverage records, independent of persistence."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum, unique
from uuid import UUID, uuid4

from trading_lab.domain.enums import MarketType
from trading_lab.domain.models import Market
from trading_lab.domain.timeframes import (
    CandleRange,
    find_candle_gaps,
    floor_to_bar,
    timeframe_delta,
)


@unique
class SyncDataset(StrEnum):
    CANDLES = "candles"
    FUNDING_RATES = "funding_rates"


@unique
class SyncStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Sync timestamps must be datetime values")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Sync timestamps must include a timezone")
    return value.astimezone(UTC)


def _count(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("Sync counts must be non-negative integers")


@dataclass(frozen=True, slots=True)
class SyncJob:
    """One explicit sync attempt; the service owns lifecycle transitions.

    last_committed_time is the highest timestamp confirmed in the database by
    this attempt, not proof of contiguous coverage and not the next fetch time.
    Empty pages never advance it. Gap repair may revisit earlier timestamps.
    SUCCEEDED describes the operation; coverage must be checked separately.
    All updates to this record and its page must commit in one transaction.
    """

    market: Market
    dataset: SyncDataset
    requested_start: datetime
    requested_end: datetime
    started_at: datetime
    timeframe: str | None = None
    id: UUID = field(default_factory=uuid4)
    status: SyncStatus = SyncStatus.PENDING
    last_committed_time: datetime | None = None
    inserted_count: int = 0
    updated_count: int = 0
    error: str | None = None
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("Sync job id must be a UUID")
        if not isinstance(self.market, Market):
            raise TypeError("Sync job market must be a Market")
        if not isinstance(self.dataset, SyncDataset) or not isinstance(self.status, SyncStatus):
            raise TypeError("Sync job dataset and status must use their enum types")
        for name in ("requested_start", "requested_end", "started_at"):
            object.__setattr__(self, name, _utc(getattr(self, name)))
        if self.requested_start >= self.requested_end:
            raise ValueError("Sync request start must be before end")
        if self.dataset is SyncDataset.CANDLES:
            CandleRange(self.requested_start, self.requested_end, self.timeframe)
        elif self.timeframe is not None or self.market.market_type is not MarketType.PERPETUAL:
            raise ValueError("Funding jobs require a perpetual market and no candle timeframe")
        _count(self.inserted_count)
        _count(self.updated_count)
        if (self.inserted_count or self.updated_count) and self.last_committed_time is None:
            raise ValueError("Non-zero write counts require a committed timestamp")
        if self.last_committed_time is not None:
            confirmed = _utc(self.last_committed_time)
            if not self.requested_start <= confirmed < self.requested_end:
                raise ValueError("Committed timestamp must lie within the requested range")
            if self.dataset is SyncDataset.CANDLES:
                if floor_to_bar(confirmed, self.timeframe) != confirmed:
                    raise ValueError("Committed candle timestamp must align to its timeframe")
            object.__setattr__(self, "last_committed_time", confirmed)
        if self.error is not None and (not isinstance(self.error, str) or not self.error.strip()):
            raise ValueError("Sync error must be a non-blank sanitized message")
        terminal = self.status in (SyncStatus.SUCCEEDED, SyncStatus.PARTIAL, SyncStatus.FAILED)
        if terminal != (self.finished_at is not None):
            raise ValueError("Only terminal sync jobs must have a finish time")
        if self.finished_at is not None:
            finished = _utc(self.finished_at)
            if finished < self.started_at:
                raise ValueError("Sync finish time must not precede its start")
            object.__setattr__(self, "finished_at", finished)
        if self.status is SyncStatus.FAILED and self.error is None:
            raise ValueError("Failed sync jobs must retain an error message")
        if self.error is not None and self.status not in (SyncStatus.FAILED, SyncStatus.PARTIAL):
            raise ValueError("Only failed or partial sync jobs may retain an error")
        if self.status is SyncStatus.PENDING:
            if self.last_committed_time is not None or self.inserted_count or self.updated_count:
                raise ValueError("Pending sync jobs must not claim committed progress")


@dataclass(frozen=True, slots=True)
class CandleCoverage:
    """Observed coverage of one checked range, not the market's listing history.

    Never derive funding completeness from this record: funding events have
    their own variable schedule. The check time is supplied by the caller.
    """

    market: Market
    requested: CandleRange
    checked_at: datetime
    candle_count: int
    first_open_time: datetime | None
    last_open_time: datetime | None
    missing_ranges: tuple[CandleRange, ...]
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.market, Market) or not isinstance(self.requested, CandleRange):
            raise TypeError("Coverage requires a Market and CandleRange")
        object.__setattr__(self, "checked_at", _utc(self.checked_at))
        _count(self.candle_count)
        if not isinstance(self.missing_ranges, tuple) or not isinstance(self.warnings, tuple):
            raise TypeError("Coverage ranges and warnings must be immutable tuples")
        if any(not isinstance(warning, str) or not warning.strip() for warning in self.warnings):
            raise ValueError("Coverage warnings must be non-blank messages")
        previous_end = self.requested.start
        for gap in self.missing_ranges:
            if not isinstance(gap, CandleRange) or gap.timeframe != self.requested.timeframe:
                raise ValueError("Coverage gaps must use the checked timeframe")
            if gap.start < previous_end or gap.end > self.requested.end:
                raise ValueError(
                    "Coverage gaps must be ordered, non-overlapping and inside the range"
                )
            previous_end = gap.end
        if self.candle_count + self.missing_bar_count != self.requested.bar_count:
            raise ValueError("Observed and missing candle counts must partition the checked range")
        if self.candle_count == 0:
            if self.first_open_time is not None or self.last_open_time is not None:
                raise ValueError("Empty coverage must not claim observed timestamps")
        else:
            first, last = _utc(self.first_open_time), _utc(self.last_open_time)
            interval = timeframe_delta(self.requested.timeframe)
            expected_first = self.requested.start
            for gap in self.missing_ranges:
                if gap.start != expected_first:
                    break
                expected_first = gap.end
            expected_end = self.requested.end
            for gap in reversed(self.missing_ranges):
                if gap.end != expected_end:
                    break
                expected_end = gap.start
            if first != expected_first or last != expected_end - interval:
                raise ValueError("Observed endpoints must match the reported missing intervals")
            object.__setattr__(self, "first_open_time", first)
            object.__setattr__(self, "last_open_time", last)

    @property
    def missing_bar_count(self) -> int:
        return sum(gap.bar_count for gap in self.missing_ranges)

    @property
    def complete(self) -> bool:
        return self.missing_bar_count == 0

    @classmethod
    def inspect(
        cls,
        market: Market,
        requested: CandleRange,
        observed_times: Iterable[datetime],
        *,
        checked_at: datetime,
        warnings: tuple[str, ...] = (),
    ) -> "CandleCoverage":
        """Consume ordered timestamps once, retaining gaps rather than all observations."""
        count = 0
        first = last = None

        def observations():
            nonlocal count, first, last
            for observed in observed_times:
                observed = _utc(observed)
                if count == 0:
                    first = observed
                last = observed
                count += 1
                yield observed

        gaps = tuple(find_candle_gaps(requested, observations()))
        return cls(market, requested, checked_at, count, first, last, gaps, warnings)
