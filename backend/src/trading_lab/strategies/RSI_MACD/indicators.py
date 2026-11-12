"""Incremental Decimal indicators shared by independent and combined strategies."""

from decimal import Decimal, localcontext


class WilderRSI:
    """Seed with SMA of the first N changes, then Wilder's recursive smoothing.

    N+1 closes produce the first value. No losses -> 100, no gains -> 0,
    and no changes at all -> neutral 50 (explicit project convention).
    """

    def __init__(self, period: int = 14):
        if type(period) is not int or not 2 <= period <= 10000:
            raise ValueError("RSI period must be an integer in [2, 10000]")
        self.period = period
        self.previous: Decimal | None = None
        self.changes = 0
        self.gain = Decimal(0)
        self.loss = Decimal(0)
        self.value: Decimal | None = None

    def update(self, close: Decimal) -> Decimal | None:
        if not isinstance(close, Decimal) or not close.is_finite() or close <= 0:
            raise ValueError("RSI close must be a finite positive Decimal")

        with localcontext() as context:
            context.prec = 50

            if self.previous is None:
                self.previous = close
                return None

            difference = close - self.previous
            self.previous = close

            gain, loss = max(difference, Decimal(0)), max(-difference, Decimal(0))

            self.changes += 1

            if self.changes <= self.period:
                self.gain += gain
                self.loss += loss
                if self.changes < self.period:
                    return None
                self.gain /= self.period
                self.loss /= self.period
            else:
                self.gain = (self.gain * (self.period - 1) + gain) / self.period
                self.loss = (self.loss * (self.period - 1) + loss) / self.period

            total = self.gain + self.loss
            self.value = Decimal(50) if total == 0 else Decimal(100) * self.gain / total
            return self.value
