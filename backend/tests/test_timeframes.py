"""Offline tests for UTC boundaries, complete candles and missing intervals."""

from datetime import UTC, datetime, timedelta, timezone
from itertools import combinations

import pytest

from trading_lab.domain.exceptions import InvalidMarketDataError
from trading_lab.domain.timeframes import (
    CandleRange,
    find_candle_gaps,
    floor_to_bar,
    timeframe_delta,
)

START = datetime(2026, 10, 31, tzinfo=UTC)
HOUR = timedelta(hours=1)


@pytest.mark.parametrize(
    ("value", "timeframe", "expected"),
    [
        (START + HOUR - timedelta(microseconds=1), "1h", START),
        (START + HOUR, "1h", START + HOUR),
        (START + timedelta(minutes=14, seconds=59), "15m", START),
        (START + timedelta(minutes=15), "15m", START + timedelta(minutes=15)),
        (START + timedelta(hours=23, minutes=59), "1d", START),
        (
            datetime(2024, 3, 1, tzinfo=UTC) - timedelta(microseconds=1),
            "1d",
            datetime(2024, 2, 29, tzinfo=UTC),
        ),
        (datetime(1969, 12, 31, 23, 59, tzinfo=UTC), "1h", datetime(1969, 12, 31, 23, tzinfo=UTC)),
    ],
)
def test_floor_uses_exact_boundaries_across_days_and_epoch(value, timeframe, expected):
    assert floor_to_bar(value, timeframe) == expected


def test_range_normalizes_offsets_and_counts_whole_bars():
    offset = timezone(timedelta(hours=2))
    requested = CandleRange(
        datetime(2026, 10, 31, 2, tzinfo=offset),
        datetime(2026, 10, 31, 5, tzinfo=offset),
        "1h",
    )
    assert requested.start == START
    assert requested.end == START + 3 * HOUR
    assert requested.start.tzinfo is UTC
    assert requested.end.tzinfo is UTC
    assert requested.bar_count == 3


@pytest.mark.parametrize("timeframe", ["", "1M", "1w", "3d", "90m", "0h", "1H"])
def test_unsupported_or_ambiguous_timeframes_are_rejected(timeframe):
    with pytest.raises(ValueError):
        timeframe_delta(timeframe)


def test_timeframe_requires_a_string():
    with pytest.raises(TypeError):
        timeframe_delta(3600)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (START, START),
        (START + HOUR, START),
        (START + timedelta(minutes=1), START + HOUR),
        (START, START + timedelta(minutes=59)),
        (START.replace(tzinfo=None), START + HOUR),
        (START, (START + HOUR).replace(tzinfo=None)),
    ],
)
def test_invalid_ranges_are_rejected_instead_of_silently_rounded(start, end):
    with pytest.raises(ValueError):
        CandleRange(start, end, "1h")


@pytest.mark.parametrize(
    ("elapsed", "expected_bars"),
    [
        (-HOUR, 0),
        (timedelta(0), 0),
        (HOUR - timedelta(microseconds=1), 0),
        (HOUR, 1),
        (2 * HOUR + timedelta(minutes=30), 2),
        (5 * HOUR, 5),
        (10 * HOUR, 5),
    ],
)
def test_sync_cutoff_excludes_unfinished_bars_and_never_extends_request(elapsed, expected_bars):
    requested = CandleRange(START, START + 5 * HOUR, "1h")
    completed = requested.completed_before(START + elapsed)

    if expected_bars == 0:
        assert completed is None
    else:
        assert completed == CandleRange(START, START + expected_bars * HOUR, "1h")
    assert requested.end == START + 5 * HOUR


def test_empty_data_reports_the_entire_requested_range_as_missing():
    requested = CandleRange(START, START + 5 * HOUR, "1h")
    assert list(find_candle_gaps(requested, iter(()))) == [requested]


def test_leading_internal_and_trailing_gaps_are_separate_ranges():
    requested = CandleRange(START, START + 5 * HOUR, "1h")
    observed = (START + index * HOUR for index in (1, 3))
    assert list(find_candle_gaps(requested, observed)) == [
        CandleRange(START, START + HOUR, "1h"),
        CandleRange(START + 2 * HOUR, START + 3 * HOUR, "1h"),
        CandleRange(START + 4 * HOUR, START + 5 * HOUR, "1h"),
    ]


def test_all_128_subsets_of_a_seven_bar_range_partition_observed_and_missing_times():
    requested = CandleRange(START, START + 7 * HOUR, "1h")
    all_times = {START + index * HOUR for index in range(7)}
    for count in range(8):
        for subset in combinations(sorted(all_times), count):
            gaps = list(find_candle_gaps(requested, iter(subset)))
            missing = set()
            for gap in gaps:
                assert gap.start >= requested.start
                assert gap.end <= requested.end
                times = {gap.start + index * HOUR for index in range(gap.bar_count)}
                assert not missing.intersection(times)
                missing.update(times)
            assert missing == all_times.difference(subset)
            assert sum(gap.bar_count for gap in gaps) + count == requested.bar_count


@pytest.mark.parametrize(
    "observed",
    [
        [START, START],
        [START + HOUR, START],
        [START - HOUR],
        [START + 5 * HOUR],
        [START + timedelta(minutes=30)],
    ],
)
def test_corrupt_timestamp_sequences_are_rejected(observed):
    requested = CandleRange(START, START + 5 * HOUR, "1h")
    with pytest.raises(InvalidMarketDataError):
        list(find_candle_gaps(requested, observed))


def test_gap_detection_normalizes_timezone_offsets():
    requested = CandleRange(START, START + HOUR, "1h")
    observed = [START.astimezone(timezone(timedelta(hours=-5)))]
    assert list(find_candle_gaps(requested, observed)) == []


def test_naive_observation_and_clock_times_are_rejected():
    requested = CandleRange(START, START + HOUR, "1h")
    with pytest.raises(ValueError):
        list(find_candle_gaps(requested, [START.replace(tzinfo=None)]))
    with pytest.raises(ValueError):
        requested.completed_before(START.replace(tzinfo=None))
