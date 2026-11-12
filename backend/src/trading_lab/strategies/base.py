"""Shared strategy contract; account settlement remains the engine's responsibility."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from trading_lab.domain.enums import DirectionMode, SignalAction
from trading_lab.domain.models import Candle


class History(Sequence[Candle]):
    """Read-only prefix; ordinary indexing/slicing cannot retrieve future candles."""

    def __init__(self, bars: tuple[Candle, ...], stop: int) -> None:
        self.__bars, self.__stop = bars, stop

    def __len__(self) -> int:
        return self.__stop

    def __getitem__(self, index):
        if isinstance(index, slice):
            return tuple(self.__bars[i] for i in range(*index.indices(self.__stop)))
        if index < 0:
            index += self.__stop
        if not 0 <= index < self.__stop:
            raise IndexError("History only exposes completed bars")
        return self.__bars[index]


@dataclass(frozen=True, slots=True)
class OrderIntent:
    action: SignalAction
    # CLOSE may partially close the remaining position. Entry always uses request allocation.
    fraction: Decimal = Decimal("1")

    def __post_init__(self):
        if not isinstance(self.action, SignalAction):
            raise TypeError("action must be a SignalAction")
        if not isinstance(self.fraction, Decimal) or not self.fraction.is_finite():
            raise ValueError("fraction must be a finite Decimal")
        if not 0 < self.fraction <= 1:
            raise ValueError("fraction must be in (0, 1]")
        if self.action is not SignalAction.CLOSE and self.fraction != 1:
            raise ValueError("Only closing orders support partial quantities")


@dataclass(frozen=True, slots=True)
class PositionView:
    side: str
    quantity: Decimal
    entry_price: Decimal


@dataclass(frozen=True, slots=True)
class StrategyContext:
    time: datetime
    history: History
    equity: Decimal
    cash: Decimal
    position: PositionView | None
    trading_enabled: bool
    direction_mode: DirectionMode = DirectionMode.LONG_ONLY


class Strategy(Protocol):
    def on_bar(self, context: StrategyContext) -> OrderIntent | None:
        """Inspect closed history only. Returned intent executes at the NEXT bar open."""
        ...
