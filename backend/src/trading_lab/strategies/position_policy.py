"""Translate indicator direction into targets allowed by the experiment."""

from trading_lab.domain.enums import DirectionMode, SignalAction
from trading_lab.strategies.base import OrderIntent


def directional_intent(*, bullish: bool, bearish: bool, mode: DirectionMode):
    if not isinstance(mode, DirectionMode):
        raise TypeError("direction mode must be a DirectionMode")
    if bullish and bearish:
        raise ValueError("Conflicting indicator directions")
    if bullish:
        return OrderIntent(
            SignalAction.CLOSE if mode is DirectionMode.SHORT_ONLY else SignalAction.TARGET_LONG
        )
    if bearish:
        return OrderIntent(
            SignalAction.CLOSE if mode is DirectionMode.LONG_ONLY else SignalAction.TARGET_SHORT
        )
    return None
