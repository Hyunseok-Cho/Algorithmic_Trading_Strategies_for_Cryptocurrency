"""Enter on an outer-band close and exit at a fixed or rolling middle band."""

from decimal import Decimal, InvalidOperation

from trading_lab.domain.enums import DirectionMode, SignalAction
from trading_lab.strategies.base import OrderIntent
from trading_lab.strategies.position_policy import directional_intent

from backend_dev.indicators.bollinger import bollinger_bands


class UserStrategy:
    strategy_version = "v1"

    def __init__(self, period=20, deviations="2", exit_middle="dynamic"):
        if type(period) is not int or period < 2:
            raise ValueError("period must be an integer >= 2")
        try:
            deviations = Decimal(str(deviations))
        except InvalidOperation:
            raise ValueError("deviations must be numeric") from None
        if not deviations.is_finite() or deviations <= 0:
            raise ValueError("deviations must be finite and positive")
        if exit_middle not in ("dynamic", "fixed"):
            raise ValueError("exit_middle must be dynamic or fixed")
        self.period = period
        self.deviations = deviations
        self.required_warmup_bars = period
        self.exit_middle = exit_middle
        self.parameters = {
            "period": period,
            "deviations": str(deviations),
            "exit_middle": exit_middle,
        }
        self.signal_bands = {}
        self._entry_middle = None

    def validate_request(self, request):
        if request.strategy_id != "bollinger_mr" or request.strategy_version != "v1":
            raise ValueError("Bollinger mean reversion requires bollinger_mr/v1")
        if request.stop_loss_pct is not None or request.take_profit_pct is not None:
            raise ValueError("Bollinger v1 requires TP/SL to be null")
        if request.warmup_bars < self.required_warmup_bars:
            raise ValueError(f"warmup_bars must be >= {self.required_warmup_bars}")

    def on_bar(self, context):
        if not context.trading_enabled or len(context.history) <= self.period:
            return None
        closes = tuple(bar.close for bar in context.history[-self.period - 1 :])
        current = bollinger_bands(closes[1:], self.deviations)
        close = closes[-1]
        if context.position is not None:
            target = self._entry_middle if self.exit_middle == "fixed" else current.middle
            reached_middle = (
                close >= target
                if context.position.side == "long"
                else close <= target
            )
            if not reached_middle:
                return None
            intent = OrderIntent(SignalAction.CLOSE)
        else:
            intent = self._entry(closes, current, context.direction_mode)
            self._entry_middle = current.middle if intent is not None else None
        if intent is not None:
            self.signal_bands[context.time] = current
        return intent

    def _entry(self, closes, current, mode):
        if current.lower == current.upper or current.lower < closes[-1] < current.upper:
            return None
        previous = bollinger_bands(closes[:-1], self.deviations)
        return directional_intent(
            bullish=(
                mode is not DirectionMode.SHORT_ONLY
                and closes[-2] > previous.lower
                and closes[-1] <= current.lower
            ),
            bearish=(
                mode is not DirectionMode.LONG_ONLY
                and closes[-2] < previous.upper
                and closes[-1] >= current.upper
            ),
            mode=mode,
        )
