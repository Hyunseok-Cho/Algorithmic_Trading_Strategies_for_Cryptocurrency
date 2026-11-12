"""Validated market data, independent of persistence and exchange SDKs."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from trading_lab.domain.enums import MarketType


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return value.astimezone(UTC)


def _decimal(value: Decimal, name: str, *, minimum: Decimal | None = None) -> None:
    # Adapters must explicitly convert source values; never Decimal(float).
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")


def _nonblank(value: str, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must not be blank")
    if value != value.strip():
        raise ValueError(f"{name} must not contain surrounding whitespace")


@dataclass(frozen=True, slots=True)
class Market:
    """Exchange market metadata, not a database row.

    Identity is (exchange, market_type, symbol). Unified and native symbols
    come from verified exchange metadata, never from string substitution.
    contract_size is base-asset quantity per contract, not leverage.
    """

    exchange: str
    market_type: MarketType
    symbol: str
    symbol_native: str
    base_asset: str
    quote_asset: str
    settle_asset: str | None = None
    contract_size: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("exchange", "symbol", "symbol_native", "base_asset", "quote_asset"):
            _nonblank(getattr(self, name), name)
        if not isinstance(self.market_type, MarketType):
            raise TypeError("market_type must be a MarketType")
        if self.market_type is MarketType.SPOT:
            if self.settle_asset is not None or self.contract_size is not None:
                raise ValueError("Spot must not specify derivative settlement or contract size")
        else:
            if self.quote_asset != "USDT" or self.settle_asset != "USDT":
                raise ValueError("Only USDT-settled linear perpetual markets are supported")
            if self.contract_size is None:
                raise ValueError("Perpetual markets require an explicit contract size")
            _decimal(self.contract_size, "contract_size", minimum=Decimal(0))
            if self.contract_size == 0:
                raise ValueError("contract_size must be positive")


@dataclass(frozen=True, slots=True)
class Candle:
    """Trade-price OHLCV; its dataset supplies the market and timeframe.

    Prices use quote-asset units per base asset. The provider normalizes
    volume to base-asset units. Mark-price candles are a separate dataset.
    Completion, timeframe alignment and sequence gaps require collection
    context and are validated by the sync service, not by this single bar.
    """

    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "open_time", _utc(self.open_time, "open_time"))
        for name in ("open", "high", "low", "close", "volume"):
            _decimal(getattr(self, name), name, minimum=Decimal(0))
        if min(self.open, self.high, self.low, self.close) == 0:
            raise ValueError("OHLC prices must be positive")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC must satisfy low <= open/close <= high")


@dataclass(frozen=True, slots=True)
class FundingRate:
    """One observed funding event; its dataset supplies the perpetual market.

    rate is a signed fraction, e.g. Decimal('0.0001') means 0.01%.
    Positive rates mean longs pay shorts. Missing events remain missing;
    this record never invents a rate or an expected funding interval.
    """

    funding_time: datetime
    rate: Decimal
    source: str
    mark_price: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "funding_time", _utc(self.funding_time, "funding_time"))
        _decimal(self.rate, "rate")
        _nonblank(self.source, "source")
        if self.mark_price is not None:
            _decimal(self.mark_price, "mark_price", minimum=Decimal(0))
            if self.mark_price == 0:
                raise ValueError("mark_price must be positive when provided")
