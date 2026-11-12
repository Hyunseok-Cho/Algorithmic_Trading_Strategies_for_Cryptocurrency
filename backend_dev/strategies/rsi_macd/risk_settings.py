"""Shared request validation for combined strategy protective exits."""

from decimal import Decimal


def validate_request(strategy, request, *, version, tp_required):
    if request.strategy_id != "rsi_macd" or request.strategy_version != version:
        raise ValueError(f"Combined {version} requires rsi_macd/{version}")
    names = ("stop_loss_pct", "take_profit_pct") if tp_required else ("stop_loss_pct",)
    for name in names:
        value = getattr(request, name)
        if not isinstance(value, Decimal) or not value.is_finite() or not 0 < value < 100:
            raise ValueError(f"Combined {version} requires {name} in (0, 100)")
    if not tp_required and request.take_profit_pct is not None:
        raise ValueError("Combined v2 forbids TP; take_profit_pct must be null")
    if request.warmup_bars < strategy.required_warmup_bars:
        raise ValueError(f"warmup_bars must be >= {strategy.required_warmup_bars}")
