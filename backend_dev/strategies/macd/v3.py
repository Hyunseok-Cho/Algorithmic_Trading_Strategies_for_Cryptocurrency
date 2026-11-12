"""MACD v3: original histogram crossings plus fixed SL and TP, no re-entry lock."""

from decimal import Decimal

from backend_dev.strategies.macd.v1 import UserStrategy as MACDv1


class UserStrategy(MACDv1):
    strategy_version = "v3"

    def validate_request(self, request):
        if request.strategy_id != "macd" or request.strategy_version != "v3":
            raise ValueError("Development MACD v3 requires macd/v3")
        for name in ("stop_loss_pct", "take_profit_pct"):
            value = getattr(request, name)
            if not isinstance(value, Decimal) or not value.is_finite() or not 0 < value < 100:
                raise ValueError(f"MACD v3 requires {name} in (0, 100)")
        if request.warmup_bars < self.required_warmup_bars:
            raise ValueError(f"warmup_bars must be >= {self.required_warmup_bars}")
