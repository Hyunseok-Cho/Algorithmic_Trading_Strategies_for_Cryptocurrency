"""Bollinger Bands calculated from a complete window of closing prices."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Bands:
    middle: Decimal
    lower: Decimal
    upper: Decimal


def bollinger_bands(closes, deviations):
    count = len(closes)
    middle = sum(closes) / count
    variance = sum((close - middle) ** 2 for close in closes) / count
    width = deviations * variance.sqrt()
    return Bands(middle, middle - width, middle + width)
