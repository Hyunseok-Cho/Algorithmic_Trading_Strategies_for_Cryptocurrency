"""Select which sides use the V4 protective-exit RSI reset."""

from decimal import Decimal, InvalidOperation

from backend_dev.strategies.rsi_macd.v4 import UserStrategy as CombinedV4

LOCK_SIDES = {
    "none": (),
    "short_only": ("short",),
    "long_only": ("long",),
    "both": ("long", "short"),
}


class UserStrategy(CombinedV4):
    strategy_version = "v5"

    def __init__(self, *args, reentry_lock="short_only", directional_protection=None, **kwargs):
        if not isinstance(reentry_lock, str) or reentry_lock not in LOCK_SIDES:
            raise ValueError("reentry_lock must be none, short_only, long_only, or both")
        super().__init__(*args, **kwargs)
        self._lock_sides = LOCK_SIDES[reentry_lock]
        self.parameters["reentry_lock"] = reentry_lock
        self.directional_protection = None
        if directional_protection is not None:
            if not isinstance(directional_protection, dict) or set(directional_protection) != {
                "long", "short",
            }:
                raise ValueError("directional_protection requires long and short settings")
            self.directional_protection = {}
            for side, protection in directional_protection.items():
                names = {"stop_loss_pct", "take_profit_pct"}
                if not isinstance(protection, dict) or set(protection) != names:
                    raise ValueError(f"{side} requires stop_loss_pct and take_profit_pct")
                try:
                    values = {name: Decimal(str(value)) for name, value in protection.items()}
                except InvalidOperation:
                    raise ValueError(f"{side} protection must be numeric") from None
                if any(not value.is_finite() or not 0 < value < 100 for value in values.values()):
                    raise ValueError(f"{side} protection must be in (0, 100)")
                self.directional_protection[side] = values
            self.parameters["directional_protection"] = self.directional_protection

    def validate_request(self, request):
        if self.directional_protection is not None:
            if request.stop_loss_pct is not None or request.take_profit_pct is not None:
                raise ValueError("Directional and common protection cannot be combined")
            request = request.model_copy(update=self.directional_protection["long"])
        super().validate_request(request)

    def on_risk_exit(self, side, reason):
        if side in self._lock_sides:
            super().on_risk_exit(side, reason)
