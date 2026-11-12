"""Reject missing input and unverified strict funding before executing a strategy."""

from trading_lab.domain.enums import FundingMode, MarketType
from trading_lab.domain.exceptions import DataCoverageError
from trading_lab.domain.timeframes import timeframe_delta


def validate_inputs(request, candles, funding):
    interval = timeframe_delta(request.timeframe)
    first = request.start_time - request.warmup_bars * interval
    expected_count = (request.end_time - first) // interval
    if len(candles) != expected_count:
        raise DataCoverageError("Stored candles do not cover the full range plus warmup")
    if any(bar.open_time != first + index * interval for index, bar in enumerate(candles)):
        raise DataCoverageError("Candles must be aligned, ascending, unique and gap-free")
    times = tuple(event.funding_time for event in funding)
    if times != tuple(sorted(set(times))):
        raise DataCoverageError("Funding events must be unique and ascending")
    if any(not request.start_time <= event.funding_time < request.end_time for event in funding):
        raise DataCoverageError("Funding events must be inside [start, end)")
    if request.market_type is MarketType.SPOT:
        if funding:
            raise ValueError("Spot must not receive funding events")
        return
    if request.funding_mode is FundingMode.STRICT:
        if request.expected_funding_times is None or not request.funding_schedule_source:
            raise DataCoverageError(
                "Strict funding requires expected_funding_times and an audited "
                "funding_schedule_source; no fixed interval is assumed"
            )
        if times != request.expected_funding_times:
            raise DataCoverageError("Stored funding events differ from the audited schedule")
        if any(event.mark_price is None for event in funding):
            raise DataCoverageError("Strict funding requires the event's historical mark price")
