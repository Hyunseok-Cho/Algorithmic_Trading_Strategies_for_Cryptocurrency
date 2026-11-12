"""Decimal EMA: seed with an N-value SMA, then use alpha=2/(N+1)."""

from decimal import Decimal, localcontext


class EMA:
    def __init__(self, period: int):
        if type(period) is not int or not 1 <= period <= 10000:
            raise ValueError("EMA period must be an integer in [1, 10000]")
        self.period = period
        self.samples = 0
        self._sum = Decimal(0)
        self.value: Decimal | None = None

    def update(self, value: Decimal) -> Decimal | None:
        # Signal EMAs consume signed MACD values, including zero.
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError("EMA input must be a finite Decimal")
        with localcontext() as context:
            context.prec = 50
            self.samples += 1
            if self.value is None:
                self._sum += value
                if self.samples < self.period:
                    return None
                self.value = self._sum / self.period
            else:
                alpha = Decimal(2) / (self.period + 1)
                self.value += alpha * (value - self.value)
            return self.value
