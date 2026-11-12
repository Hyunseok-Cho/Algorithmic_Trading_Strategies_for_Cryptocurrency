"""Market fills with adverse, explicitly configured slippage."""

from decimal import Decimal


def execution_price(price: Decimal, *, buy: bool, slippage_bps: Decimal) -> Decimal:
    return price * (1 + (1 if buy else -1) * slippage_bps / Decimal(10000))
