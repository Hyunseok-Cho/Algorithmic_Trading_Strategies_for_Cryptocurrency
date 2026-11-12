"""Validate market data contracts without a database or exchange connection."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_lab.domain.enums import MarketType
from trading_lab.domain.models import Candle, FundingRate, Market


@pytest.fixture
def candle():
    return Candle(
        open_time=datetime(2026, 10, 31, tzinfo=UTC),
        open=Decimal("100.000000000000000001"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("0"),
    )


def test_candle_preserves_decimal_precision_and_allows_zero_volume(candle):
    assert candle.open == Decimal("100.000000000000000001")
    assert candle.open != Decimal("100")
    assert candle.volume == 0


def test_flat_price_candle_is_valid(candle):
    flat = replace(
        candle, open=Decimal("100"), high=Decimal("100"), low=Decimal("100"), close=Decimal("100")
    )
    assert flat.open == flat.high == flat.low == flat.close


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("open", 100.0, TypeError),
        ("close", "105", TypeError),
        ("volume", 1, TypeError),
        ("open_time", "2026-10-31T00:00:00Z", TypeError),
        ("open_time", datetime(2026, 10, 31), ValueError),
        ("open", Decimal("0"), ValueError),
        ("close", Decimal("-1"), ValueError),
        ("volume", Decimal("-0.01"), ValueError),
        ("high", Decimal("104"), ValueError),
        ("low", Decimal("101"), ValueError),
        ("high", Decimal("80"), ValueError),
        ("close", Decimal("NaN"), ValueError),
        ("volume", Decimal("Infinity"), ValueError),
    ],
)
def test_invalid_candle_is_rejected(candle, field, value, error):
    with pytest.raises(error):
        replace(candle, **{field: value})


def test_observation_times_normalize_to_same_utc_instant(candle):
    local = datetime(2026, 10, 31, 2, tzinfo=timezone(timedelta(hours=2)))
    normalized = replace(candle, open_time=local)
    funding = FundingRate(local, Decimal("0.0001"), "binance")

    assert normalized.open_time == funding.funding_time == candle.open_time
    assert normalized.open_time.tzinfo is UTC
    assert funding.funding_time.tzinfo is UTC


def test_spot_and_perpetual_are_distinct_markets():
    spot = Market("binance", MarketType.SPOT, "BTC/USDT", "BTCUSDT", "BTC", "USDT")
    perpetual = Market(
        "binance",
        MarketType.PERPETUAL,
        "BTC/USDT:USDT",
        "BTCUSDT",
        "BTC",
        "USDT",
        settle_asset="USDT",
        contract_size=Decimal("1"),
    )

    assert spot.symbol_native == perpetual.symbol_native
    assert (spot.exchange, spot.market_type, spot.symbol) != (
        perpetual.exchange,
        perpetual.market_type,
        perpetual.symbol,
    )
    assert spot.contract_size is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"exchange": ""},
        {"symbol": " BTC/USDT"},
        {"base_asset": " "},
        {"symbol_native": None},
        {"market_type": "spot"},
        {"settle_asset": "USDT"},
        {"contract_size": Decimal("1")},
        {"market_type": MarketType.PERPETUAL},
        {
            "market_type": MarketType.PERPETUAL,
            "settle_asset": "USDT",
            "contract_size": Decimal("0"),
        },
        {
            "market_type": MarketType.PERPETUAL,
            "settle_asset": "USDT",
            "contract_size": Decimal("-1"),
        },
        {"market_type": MarketType.PERPETUAL, "settle_asset": "USDT", "contract_size": 1.0},
        {
            "market_type": MarketType.PERPETUAL,
            "settle_asset": "USDT",
            "contract_size": Decimal("NaN"),
        },
        {
            "market_type": MarketType.PERPETUAL,
            "quote_asset": "USD",
            "settle_asset": "BTC",
            "contract_size": Decimal("100"),
        },
    ],
)
def test_invalid_or_unsupported_market_is_rejected(overrides):
    values = dict(
        exchange="binance",
        market_type=MarketType.SPOT,
        symbol="BTC/USDT",
        symbol_native="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
    )
    values.update(overrides)
    with pytest.raises((ValueError, TypeError)):
        Market(**values)


@pytest.mark.parametrize("rate", [Decimal("-0.0001"), Decimal("0"), Decimal("0.0001")])
def test_observed_funding_rate_keeps_its_sign_and_optional_mark_price(candle, rate):
    event = FundingRate(candle.open_time, rate, "binance")
    assert event.rate == rate
    assert event.mark_price is None
    assert replace(event, mark_price=Decimal("100")).mark_price == Decimal("100")


@pytest.mark.parametrize(
    "overrides",
    [
        {"rate": None},
        {"rate": 0.0001},
        {"rate": Decimal("NaN")},
        {"rate": Decimal("-Infinity")},
        {"source": ""},
        {"source": " binance "},
        {"funding_time": datetime(2026, 10, 31)},
        {"mark_price": Decimal("0")},
        {"mark_price": Decimal("-1")},
        {"mark_price": Decimal("NaN")},
        {"mark_price": 100.0},
    ],
)
def test_missing_or_invalid_funding_is_not_silently_replaced_with_zero(candle, overrides):
    event = FundingRate(candle.open_time, Decimal("0.0001"), "binance")
    with pytest.raises((ValueError, TypeError)):
        replace(event, **overrides)


def test_validated_records_cannot_be_mutated(candle):
    records = (
        (candle, "close", Decimal("0")),
        (
            Market("binance", MarketType.SPOT, "BTC/USDT", "BTCUSDT", "BTC", "USDT"),
            "market_type",
            MarketType.PERPETUAL,
        ),
        (FundingRate(candle.open_time, Decimal("0.0001"), "binance"), "rate", None),
    )
    for record, field, value in records:
        with pytest.raises(FrozenInstanceError):
            setattr(record, field, value)
