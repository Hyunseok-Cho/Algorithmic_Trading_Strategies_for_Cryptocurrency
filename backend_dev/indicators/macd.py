"""MACD=EMA(fast)-EMA(slow); signal=EMA(MACD); histogram=MACD-signal."""

from dataclasses import dataclass
from decimal import Decimal, localcontext

from backend_dev.indicators.ema import EMA


@dataclass(frozen=True, slots=True)
class MACDValue:
    macd: Decimal
    signal: Decimal
    histogram: Decimal


class MACD:
    def __init__(self, fast=12, slow=26, signal=9):
        for name, period in (("fast", fast), ("slow", slow), ("signal", signal)):
            if type(period) is not int or not 1 <= period <= 10000:
                raise ValueError(f"{name} must be an integer in [1, 10000]")
        if fast >= slow:
            raise ValueError("MACD requires fast < slow")
        self.fast, self.slow, self.signal_period = fast, slow, signal
        self._fast, self._slow, self._signal = EMA(fast), EMA(slow), EMA(signal)
        self.value: MACDValue | None = None

    def update(self, close: Decimal) -> MACDValue | None:
        if not isinstance(close, Decimal) or not close.is_finite() or close <= 0:
            raise ValueError("MACD close must be a finite positive Decimal")
        with localcontext() as context:
            context.prec = 50
            fast, slow = self._fast.update(close), self._slow.update(close)
            if fast is None or slow is None:
                return None
            macd = fast - slow
            signal = self._signal.update(macd)
            if signal is None:
                return None
            self.value = MACDValue(macd, signal, macd - signal)
            return self.value
