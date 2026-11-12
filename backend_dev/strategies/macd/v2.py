"""MACD v2: original histogram crossings plus fixed entry-price SL, no TP."""

from decimal import Decimal

from backend_dev.strategies.macd.v1 import UserStrategy as MACDv1


class UserStrategy(MACDv1):
    strategy_version = "v2"

    def validate_request(self, request):
        if request.strategy_id != "macd" or request.strategy_version != "v2":
            raise ValueError("Development MACD v2 requires macd/v2")
        if (
            not isinstance(request.stop_loss_pct, Decimal)
            or not request.stop_loss_pct.is_finite()
            or not 0 < request.stop_loss_pct < 100
        ):
            raise ValueError("MACD v2 requires stop_loss_pct in (0, 100)")
        if request.take_profit_pct is not None:
            raise ValueError("MACD v2 forbids TP; take_profit_pct must be null")
        if request.warmup_bars < self.required_warmup_bars:
            raise ValueError(f"warmup_bars must be >= {self.required_warmup_bars}")
