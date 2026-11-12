"""Decimal settlement arithmetic; account amounts settle to 12 decimal places."""

from decimal import ROUND_HALF_EVEN, Decimal

MONEY_QUANTUM = Decimal("0.000000000001")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)


def price_pnl(side: str, quantity: Decimal, entry: Decimal, exit_price: Decimal) -> Decimal:
    return money((1 if side == "long" else -1) * quantity * (exit_price - entry))
