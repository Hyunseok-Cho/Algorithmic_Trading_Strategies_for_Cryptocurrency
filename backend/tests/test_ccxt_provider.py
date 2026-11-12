"""Offline Binance adapter tests using real CCXT parsers and mocked endpoints."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, call

import ccxt
import pytest

from trading_lab.domain.enums import MarketType
from trading_lab.domain.exceptions import (
    FundingHistoryUnavailableError,
    InvalidMarketDataError,
    ProviderError,
    TransientProviderError,
    UnsupportedMarketError,
    UnsupportedTimeframeError,
)
from trading_lab.infrastructure.exchanges.ccxt_provider import CCXTProvider

START = datetime(2026, 10, 31, tzinfo=UTC)
END = START + timedelta(hours=1)
STAMP = 1793404800000


@pytest.fixture(autouse=True)
def forbid_http(monkeypatch):
    monkeypatch.setattr(
        ccxt.Exchange,
        "fetch",
        Mock(side_effect=AssertionError("Provider unit tests must never make an HTTP request")),
    )


@pytest.fixture
def provider_factory():
    providers = []

    def create(market_type=MarketType.SPOT, **kwargs):
        spot = market_type is MarketType.SPOT
        client = ccxt.binance() if spot else ccxt.binanceusdm()
        symbol = "BTC/USDT" if spot else "BTC/USDT:USDT"
        metadata = dict(
            id="BTCUSDT",
            symbol=symbol,
            base="BTC",
            quote="USDT",
            spot=spot,
            contract=not spot,
            swap=not spot,
            future=False,
            linear=not spot,
            inverse=False,
            option=False,
            settle=None if spot else "USDT",
            contractSize=None if spot else "1",
            expiry=None,
            type="spot" if spot else "swap",
        )
        client.markets = {symbol: metadata}
        client.markets_by_id = {"BTCUSDT": [metadata]}
        client.load_markets = Mock(return_value=client.markets)
        client.publicGetKlines = Mock(return_value=[])
        client.fapiPublicGetKlines = Mock(return_value=[])
        client.fapiPublicGetFundingRate = Mock(return_value=[])
        sleeper = Mock()
        provider = CCXTProvider(market_type, client=client, sleep=sleeper, **kwargs)
        providers.append(provider)
        return provider, client, metadata, sleeper

    try:
        yield create
    finally:
        for provider in providers:
            provider.close()


def raw_candle(timestamp=STAMP, close="105"):
    return [
        timestamp,
        "100.000000000000000001",
        "110",
        "90",
        close,
        "0",
        timestamp + 3599999,
        "0",
        0,
        "0",
        "0",
        "0",
    ]


def fetch_candles(provider, market, *, limit=10, timeframe="1h"):
    return provider.fetch_candles(market, timeframe, start=START, end=END, limit=limit)


def test_creation_is_network_free_and_metadata_load_is_cached(provider_factory):
    provider, client, metadata, _ = provider_factory()
    client.load_markets.assert_not_called()
    provider.get_market(metadata["symbol"])
    provider.get_market(metadata["symbol"])
    client.load_markets.assert_called_once_with()
    assert client.enableRateLimit is True
    assert client.options["maxRetriesOnFailure"] == 0
    assert not client.apiKey and not client.secret


@pytest.mark.parametrize("market_type", [MarketType.SPOT, MarketType.PERPETUAL])
def test_real_ccxt_ohlcv_parser_preserves_decimal_strings_and_request_bounds(
    provider_factory, market_type
):
    provider, client, metadata, _ = provider_factory(market_type)
    endpoint = (
        client.publicGetKlines if market_type is MarketType.SPOT else client.fapiPublicGetKlines
    )
    endpoint.return_value = [raw_candle()]

    records = fetch_candles(provider, provider.get_market(metadata["symbol"]))

    assert records[0].open == Decimal("100.000000000000000001")
    assert records[0].open != Decimal("100")
    assert records[0].volume == Decimal("0")
    assert records[0].open_time == START
    request = endpoint.call_args.args[0]
    assert request["startTime"] == STAMP
    assert request["endTime"] == STAMP + 3599999
    endpoint.assert_called_once()


@pytest.mark.parametrize("rate", ["-0.0001", "0", "0.0001"])
@pytest.mark.parametrize("mark", [None, "", "100.000000000000000001"])
def test_real_ccxt_funding_parser_preserves_sign_precision_and_optional_mark(
    provider_factory, rate, mark
):
    provider, client, metadata, _ = provider_factory(MarketType.PERPETUAL)
    raw = dict(symbol="BTCUSDT", fundingTime=STAMP, fundingRate=rate)
    if mark is not None:
        raw["markPrice"] = mark
    client.fapiPublicGetFundingRate.return_value = [raw]

    records = provider.fetch_funding_rates(
        provider.get_market(metadata["symbol"]), start=START, end=END, limit=10
    )

    assert records[0].rate == Decimal(rate)
    assert records[0].mark_price == (None if mark in (None, "") else Decimal(mark))
    assert records[0].funding_time == START
    assert client.fapiPublicGetFundingRate.call_args.args[0]["endTime"] == STAMP + 3599999


def test_timeout_retries_then_succeeds_without_real_sleep(provider_factory):
    provider, client, metadata, sleeper = provider_factory(max_retries=2)
    client.publicGetKlines.side_effect = [ccxt.RequestTimeout("synthetic"), [raw_candle()]]
    assert len(fetch_candles(provider, provider.get_market(metadata["symbol"]))) == 1
    assert client.publicGetKlines.call_count == 2
    sleeper.assert_called_once_with(1.0)


def test_retry_exhaustion_is_bounded_and_keeps_original_cause(provider_factory):
    provider, client, metadata, sleeper = provider_factory(max_retries=2)
    failure = ccxt.ExchangeNotAvailable("synthetic")
    client.publicGetKlines.side_effect = failure
    with pytest.raises(TransientProviderError) as captured:
        fetch_candles(provider, provider.get_market(metadata["symbol"]))
    assert captured.value.__cause__ is failure
    assert client.publicGetKlines.call_count == 3
    assert sleeper.call_args_list == [call(1.0), call(2.0)]


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (ccxt.BadSymbol("synthetic"), UnsupportedMarketError),
        (ccxt.NotSupported("synthetic"), UnsupportedTimeframeError),
        (ccxt.AuthenticationError("synthetic"), ProviderError),
        (ccxt.DDoSProtection("synthetic"), ProviderError),
    ],
)
def test_permanent_errors_stop_immediately(provider_factory, failure, expected):
    provider, client, metadata, sleeper = provider_factory()
    client.publicGetKlines.side_effect = failure
    with pytest.raises(expected):
        fetch_candles(provider, provider.get_market(metadata["symbol"]))
    client.publicGetKlines.assert_called_once()
    sleeper.assert_not_called()


def test_rate_limit_honors_retry_after(provider_factory):
    provider, client, metadata, sleeper = provider_factory()
    client.last_response_headers = {"Retry-After": "5"}
    client.publicGetKlines.side_effect = [ccxt.RateLimitExceeded("synthetic"), []]
    assert fetch_candles(provider, provider.get_market(metadata["symbol"])) == []
    sleeper.assert_called_once_with(5.0)


@pytest.mark.parametrize("retry_after", ["61", "unknown", "NaN", "Infinity"])
def test_long_or_unknown_retry_delay_stops_instead_of_retrying_early(provider_factory, retry_after):
    provider, client, metadata, sleeper = provider_factory()
    client.last_response_headers = {"Retry-After": retry_after}
    client.publicGetKlines.side_effect = ccxt.RateLimitExceeded("synthetic")
    with pytest.raises(TransientProviderError):
        fetch_candles(provider, provider.get_market(metadata["symbol"]))
    client.publicGetKlines.assert_called_once()
    sleeper.assert_not_called()


def test_identical_duplicates_collapse_but_conflicting_values_raise(provider_factory):
    provider, client, metadata, _ = provider_factory()
    market = provider.get_market(metadata["symbol"])
    client.publicGetKlines.return_value = [raw_candle(), raw_candle()]
    assert len(fetch_candles(provider, market)) == 1
    client.publicGetKlines.return_value = [raw_candle(), raw_candle(close="104")]
    with pytest.raises(InvalidMarketDataError):
        fetch_candles(provider, market)


@pytest.mark.parametrize(
    "page",
    [
        None,
        {},
        [[STAMP, "100"]],
        [[STAMP, 100.0, "110", "90", "105", "0"]],
        [[STAMP, "100", "99", "90", "105", "0"]],
        [[STAMP, "NaN", "110", "90", "105", "0"]],
        [[STAMP + 1, "100", "110", "90", "105", "0"]],
    ],
)
def test_malformed_normalized_candle_pages_raise_without_retry(provider_factory, page):
    provider, client, metadata, sleeper = provider_factory()
    client.fetch_ohlcv = Mock(return_value=page)
    with pytest.raises(InvalidMarketDataError):
        fetch_candles(provider, provider.get_market(metadata["symbol"]))
    client.fetch_ohlcv.assert_called_once()
    sleeper.assert_not_called()


def test_normalized_pages_are_filtered_to_half_open_range(provider_factory):
    provider, client, metadata, _ = provider_factory()
    client.fetch_ohlcv = Mock(
        return_value=[
            [timestamp, "100", "110", "90", "105", "0"]
            for timestamp in (STAMP - 3600000, STAMP, STAMP + 3600000)
        ]
    )
    records = fetch_candles(provider, provider.get_market(metadata["symbol"]))
    assert [record.open_time for record in records] == [START]


@pytest.mark.parametrize("limit", [0, 1001, True, 1.5])
def test_invalid_limit_is_rejected_before_endpoint_call(provider_factory, limit):
    provider, client, metadata, _ = provider_factory()
    with pytest.raises(ValueError):
        fetch_candles(provider, provider.get_market(metadata["symbol"]), limit=limit)
    client.publicGetKlines.assert_not_called()


def test_exchange_timeframe_support_is_separate_from_engine_interval_support(provider_factory):
    provider, client, metadata, _ = provider_factory()
    with pytest.raises(UnsupportedTimeframeError):
        provider.fetch_candles(
            provider.get_market(metadata["symbol"]),
            "3h",
            start=START,
            end=START + timedelta(hours=3),
            limit=10,
        )
    client.publicGetKlines.assert_not_called()


def test_symbol_aliases_and_stale_market_metadata_are_not_accepted(provider_factory):
    provider, client, metadata, _ = provider_factory()
    with pytest.raises(UnsupportedMarketError):
        provider.get_market("BTCUSDT")
    market = provider.get_market(metadata["symbol"])
    with pytest.raises(InvalidMarketDataError):
        fetch_candles(provider, replace(market, symbol_native="OTHER"))
    client.publicGetKlines.assert_not_called()


@pytest.mark.parametrize(
    "change", [{"inverse": True}, {"swap": False}, {"settle": "BTC"}, {"expiry": STAMP}]
)
def test_inverse_dated_or_wrong_settlement_contracts_are_rejected(provider_factory, change):
    provider, _, metadata, _ = provider_factory(MarketType.PERPETUAL)
    metadata.update(change)
    with pytest.raises(UnsupportedMarketError):
        provider.get_market(metadata["symbol"])


def test_spot_funding_is_explicitly_unsupported(provider_factory):
    provider, client, metadata, _ = provider_factory()
    assert provider.supports_funding_history is False
    with pytest.raises(FundingHistoryUnavailableError):
        provider.fetch_funding_rates(
            provider.get_market(metadata["symbol"]), start=START, end=END, limit=10
        )
    client.fapiPublicGetFundingRate.assert_not_called()


def test_unsupported_funding_capability_does_not_turn_into_empty_history(provider_factory):
    provider, client, metadata, _ = provider_factory(MarketType.PERPETUAL)
    client.has["fetchFundingRateHistory"] = False
    with pytest.raises(FundingHistoryUnavailableError):
        provider.fetch_funding_rates(
            provider.get_market(metadata["symbol"]), start=START, end=END, limit=10
        )
    client.fapiPublicGetFundingRate.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"fundingRate": None},
        {"fundingRate": "NaN"},
        {"symbol": "ETH/USDT:USDT"},
        {"info": ["invalid"]},
    ],
)
def test_invalid_funding_events_are_not_replaced_with_zero(provider_factory, change):
    provider, client, metadata, _ = provider_factory(MarketType.PERPETUAL)
    event = dict(symbol=metadata["symbol"], timestamp=STAMP, fundingRate="0.0001", info={})
    event.update(change)
    client.fetch_funding_rate_history = Mock(return_value=[event])
    with pytest.raises(InvalidMarketDataError):
        provider.fetch_funding_rates(
            provider.get_market(metadata["symbol"]), start=START, end=END, limit=10
        )


def test_close_is_idempotent_and_cached_metadata_cannot_be_used_after_close(provider_factory):
    provider, client, metadata, _ = provider_factory()
    provider.get_market(metadata["symbol"])
    original_close = client.close
    client.close = Mock(wraps=original_close)
    provider.close()
    provider.close()
    client.close.assert_called_once()
    with pytest.raises(ProviderError):
        provider.get_market(metadata["symbol"])
