"""MACD v1: histogram zero crossings; opposite crossings exit/reverse."""

from trading_lab.strategies.base import OrderIntent, StrategyContext
from trading_lab.strategies.position_policy import directional_intent

from backend_dev.indicators.macd import MACD


class UserStrategy:
    strategy_version = "v1"

    def __init__(self, fast=12, slow=26, signal=9):
        self._macd = MACD(fast, slow, signal)
        self.parameters = {"fast": fast, "slow": slow, "signal": signal}
        # First full value needs slow+signal-1 closes. One preceding value is
        # required to detect a crossing on the first analysis candle.
        self.required_warmup_bars = slow + signal - 1
        self._processed = 0
        self._previous_histogram = None
        self._last_open_time = None

    def validate_request(self, request):
        if request.strategy_id != "macd" or request.strategy_version != "v1":
            raise ValueError("Development MACD v1 requires macd/v1")
        if request.stop_loss_pct is not None or request.take_profit_pct is not None:
            raise ValueError("MACD v1 uses opposite crossings; TP/SL must be null")
        if request.warmup_bars < self.required_warmup_bars:
            raise ValueError(f"warmup_bars must be >= {self.required_warmup_bars}")

    def on_bar(self, context: StrategyContext) -> OrderIntent | None:
        if len(context.history) < self._processed:
            raise ValueError("Use a new strategy for an earlier history")
        if (
            self._processed
            and context.history[self._processed - 1].open_time != self._last_open_time
        ):
            raise ValueError("History changed; use a new strategy")
        intent = None
        for index in range(self._processed, len(context.history)):
            candle = context.history[index]
            value = self._macd.update(candle.close)
            previous = self._previous_histogram
            if value is not None:
                histogram = value.histogram
                self._previous_histogram = histogram
                # Catch up indicator state without issuing orders for older bars.
                if (
                    index == len(context.history) - 1
                    and context.trading_enabled
                    and previous is not None
                ):
                    intent = directional_intent(
                        bullish=previous <= 0 and histogram > 0,
                        bearish=previous >= 0 and histogram < 0,
                        mode=context.direction_mode,
                    )
            self._last_open_time = candle.open_time
        self._processed = len(context.history)
        return intent
