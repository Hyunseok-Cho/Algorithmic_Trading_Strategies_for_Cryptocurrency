"""Fixed UTC candle boundaries and gap inspection, without external data access."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from trading_lab.domain.exceptions import InvalidMarketDataError

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_INTERVALS = {
    "1m": timedelta(minutes=1),
    "3m": timedelta(minutes=3),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "2h": timedelta(hours=2),
    "3h": timedelta(hours=3),
    "4h": timedelta(hours=4),
    "6h": timedelta(hours=6),
    "8h": timedelta(hours=8),
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
}


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Candle times must be datetime values")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Candle times must include a timezone")
    return value.astimezone(UTC)


def timeframe_delta(timeframe: str) -> timedelta:
    """Return an engine-supported fixed interval, not exchange capability.

    The provider must separately verify the exchange supports this interval.
    Calendar months/weeks and multi-day exchange-specific anchors require a
    different alignment model and are deliberately rejected here.
    """
    if not isinstance(timeframe, str):
        raise TypeError("timeframe must be a string")
    try:
        return _INTERVALS[timeframe]
    except KeyError:
        raise ValueError(f"Unsupported fixed UTC timeframe: {timeframe}") from None


def floor_to_bar(value: datetime, timeframe: str) -> datetime:
    """Return the UTC start of the containing bar, using exact timedelta arithmetic.

    At this returned boundary all preceding bars are complete. A bar opening
    at the boundary is not complete yet, including when value is exactly on it.
    """
    value = _as_utc(value)
    interval = timeframe_delta(timeframe)
    return _EPOCH + ((value - _EPOCH) // interval) * interval


@dataclass(frozen=True, slots=True)
class CandleRange:
    """A non-empty UTC [start, end) range of whole, aligned candles.

    Reject unaligned user boundaries rather than silently rounding the
    requested experiment. Warmup is a separate explicitly extended range.
    """

    start: datetime
    end: datetime
    timeframe: str

    def __post_init__(self) -> None:
        start, end = _as_utc(self.start), _as_utc(self.end)
        if start >= end:
            raise ValueError("Candle range start must be before end")
        if floor_to_bar(start, self.timeframe) != start:
            raise ValueError("Candle range start must align to its UTC timeframe")
        if floor_to_bar(end, self.timeframe) != end:
            raise ValueError("Candle range end must align to its UTC timeframe")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    @property
    def bar_count(self) -> int:
        return (self.end - self.start) // timeframe_delta(self.timeframe)

    def completed_before(self, now: datetime) -> "CandleRange | None":
        """Limit sync to complete bars at the caller's captured clock time.

        None means there are no complete requested bars yet. This does not
        establish exchange availability or guarantee stored data coverage.
        """
        end = min(self.end, floor_to_bar(now, self.timeframe))
        return None if end <= self.start else replace(self, end=end)


def find_candle_gaps(
    requested: CandleRange, observed_times: Iterable[datetime]
) -> Iterator[CandleRange]:
    """Yield missing intervals, including leading/trailing gaps, without filling them.

    Input must be strictly ascending, unique and within the requested range.
    Consume the iterator fully to validate all observations. Missing intervals
    only indicate absent records; they do not prove exchange/API failure or
    that a market existed during the interval.
    """
    interval = timeframe_delta(requested.timeframe)
    expected = requested.start
    for raw_time in observed_times:
        observed = _as_utc(raw_time)
        if not requested.start <= observed < requested.end:
            raise InvalidMarketDataError("Observed candle time lies outside the requested range")
        if floor_to_bar(observed, requested.timeframe) != observed:
            raise InvalidMarketDataError("Observed candle time is not aligned to the UTC timeframe")
        if observed < expected:
            raise InvalidMarketDataError(
                "Observed candle times must be strictly ascending and unique"
            )
        if observed > expected:
            yield CandleRange(expected, observed, requested.timeframe)
        expected = observed + interval
    if expected < requested.end:
        yield CandleRange(expected, requested.end, requested.timeframe)
