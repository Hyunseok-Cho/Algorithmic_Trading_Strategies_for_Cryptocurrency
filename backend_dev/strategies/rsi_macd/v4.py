"""BTC perpetual variant with an RSI reset after a protective exit."""

from trading_lab.domain.enums import MarketType

from backend_dev.strategies.rsi_macd.risk_settings import validate_request
from backend_dev.strategies.rsi_macd.v1 import UserStrategy as CombinedV1


class UserStrategy(CombinedV1):
    strategy_version = "v4"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._locked_sides = set()
        self.parameters["reentry_rule"] = "rsi_reset_after_sl_or_tp"

    def validate_request(self, request):
        if (
            request.market_type is not MarketType.PERPETUAL
            or request.symbol != "BTC/USDT:USDT"
            or request.timeframe != "1h"
        ):
            raise ValueError(f"Combined {self.strategy_version} requires BTC/USDT:USDT perpetual 1h")
        validate_request(
            self, request, version=self.strategy_version, tp_required=request.take_profit_pct is not None
        )

    def on_risk_exit(self, side, reason):
        if reason in ("stop_loss", "take_profit"):
            self._locked_sides.add(side)

    def _entries(self, rsi, macd):
        if rsi >= self.lower:
            self._locked_sides.discard("long")
        if rsi <= self.upper:
            self._locked_sides.discard("short")
        long_entry, short_entry = super()._entries(rsi, macd)
        return long_entry and "long" not in self._locked_sides, (
            short_entry and "short" not in self._locked_sides
        )
