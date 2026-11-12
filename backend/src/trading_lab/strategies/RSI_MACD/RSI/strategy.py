"""RSI v1: original threshold-based exits/reversals; baseline trading logic."""

from decimal import Decimal

from trading_lab.strategies.base import StrategyContext, OrderIntent
from trading_lab.strategies.position_policy import directional_intent
from trading_lab.strategies.RSI_MACD.indicators import WilderRSI

class UserStrategy:
    def __init__(self, period=14, lower="38", upper="70"):
        self.period = period
        self.lower = Decimal(str(lower))
        self.upper = Decimal(str(upper))

        if type(period) is not int or not 2 <= period <= 10000:
            raise ValueError("period should be an integer between 2 and 10000")

        if not self.lower.is_finite() or not self.upper.is_finite():
            raise ValueError("lower, upper should be finite numbers")
        if not 0 < self.lower < self.upper < 100:
            raise ValueError("Should be 0 < lower < upper < 100.")

        self._rsi = WilderRSI(period)
        self._processed = 0

        self.required_warmup_bars = period

        self.parameters = {
            "period": period,
            "lower": str(self.lower),
            "upper": str(self.upper)
        }

    def on_bar(self, context: StrategyContext) -> OrderIntent | None:
        if len(context.history) < self._processed:
            raise ValueError("Use a new strategy instance for an earlier history")

        for index in range(self._processed, len(context.history)):
            candle = context.history[index]
            self._rsi.update(candle.close)

        self._processed = len(context.history)

        rsi = self._rsi.value

        if rsi is None:
            return None

        if not context.trading_enabled:
            return None

        return directional_intent(
            bullish=rsi < self.lower,
            bearish=rsi > self.upper,
            mode=context.direction_mode
        )
