"""Combined v1: MACD-vs-Signal state filters RSI entries; RSI exits independently.

Shared WilderRSI is imported from the unchanged backend. No TP/SL. A MACD
direction change alone never exits; reversal requires the opposite RSI band
and the opposite MACD filter together.
"""

from decimal import Decimal, InvalidOperation

from trading_lab.domain.enums import DirectionMode, SignalAction
from trading_lab.strategies.base import OrderIntent, StrategyContext
from trading_lab.strategies.position_policy import directional_intent
from trading_lab.strategies.RSI_MACD.indicators import WilderRSI

from backend_dev.indicators.macd import MACD


class UserStrategy:
    strategy_version = "v1"

    def __init__(self, rsi_period=14, lower="38", upper="70", fast=12, slow=26, signal=9):
        self._rsi = WilderRSI(rsi_period)
        self._macd = MACD(fast, slow, signal)
        try:
            self.lower, self.upper = Decimal(str(lower)), Decimal(str(upper))
        except InvalidOperation:
            raise ValueError("RSI thresholds must be numeric") from None
        if not self.lower.is_finite() or not self.upper.is_finite():
            raise ValueError("RSI thresholds must be finite")
        if not 0 < self.lower < self.upper < 100:
            raise ValueError("Require 0 < lower < upper < 100")
        self.parameters = {
            "rsi_period": rsi_period,
            "lower": str(self.lower),
            "upper": str(self.upper),
            "fast": fast,
            "slow": slow,
            "signal": signal,
            "macd_filter": "macd_vs_signal_state",
            "exit_rule": "opposite_rsi_threshold",
        }
        self.required_warmup_bars = max(rsi_period, slow + signal - 1)
        self._processed = 0
        self._last_open_time = None

    def validate_request(self, request):
        if request.strategy_id != "rsi_macd" or request.strategy_version != "v1":
            raise ValueError("Combined strategy requires rsi_macd/v1")
        if request.stop_loss_pct is not None or request.take_profit_pct is not None:
            raise ValueError("Combined v1 requires TP/SL to be null")
        if request.warmup_bars < self.required_warmup_bars:
            raise ValueError(f"warmup_bars must be >= {self.required_warmup_bars}")

    def _entries(self, rsi, macd):
        return (
            macd.macd > macd.signal and rsi < self.lower,
            macd.macd < macd.signal and rsi > self.upper,
        )

    def _decide(self, rsi, macd, context):
        long_entry, short_entry = self._entries(rsi, macd)
        position = context.position
        if position is not None:
            exit_long = position.side == "long" and rsi > self.upper
            exit_short = position.side == "short" and rsi < self.lower
            if not (exit_long or exit_short):
                return None
            # Exit is unconditional on MACD. Reverse only if the new entry also qualifies.
            if exit_long and short_entry or exit_short and long_entry:
                return directional_intent(
                    bullish=long_entry,
                    bearish=short_entry,
                    mode=context.direction_mode,
                )
            return OrderIntent(SignalAction.CLOSE)
        if long_entry and context.direction_mode is not DirectionMode.SHORT_ONLY:
            return directional_intent(bullish=True, bearish=False, mode=context.direction_mode)
        if short_entry and context.direction_mode is not DirectionMode.LONG_ONLY:
            return directional_intent(bullish=False, bearish=True, mode=context.direction_mode)
        return None

    def on_bar(self, context: StrategyContext) -> OrderIntent | None:
        size = len(context.history)
        if size < self._processed:
            raise ValueError("Use a new strategy for an earlier history")
        if (
            self._processed
            and context.history[self._processed - 1].open_time != self._last_open_time
        ):
            raise ValueError("History changed; use a new strategy")
        if size == self._processed:
            return None
        for index in range(self._processed, size):
            candle = context.history[index]
            self._rsi.update(candle.close)
            self._macd.update(candle.close)
            self._last_open_time = candle.open_time
        self._processed = size
        if not context.trading_enabled or self._rsi.value is None or self._macd.value is None:
            return None
        return self._decide(self._rsi.value, self._macd.value, context)
