"""Public Binance data through CCXT; no database, API keys or order execution."""

import math
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import ccxt

from trading_lab.domain.enums import MarketType
from trading_lab.domain.exceptions import (
    FundingHistoryUnavailableError,
    InvalidMarketDataError,
    ProviderError,
    TransientProviderError,
    UnsupportedMarketError,
    UnsupportedTimeframeError,
)
from trading_lab.domain.models import Candle, FundingRate, Market
from trading_lab.domain.timeframes import CandleRange, floor_to_bar

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MILLISECOND = timedelta(milliseconds=1)
_MAX_RETRY_DELAY = 60.0


def _decimal(value: Any) -> Decimal:
    # CCXT's number=str retains exchange decimal strings before domain conversion.
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        raise ValueError("Expected an exact numeric value")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("Expected a finite numeric value")
    return result


def _datetime(timestamp: Any) -> datetime:
    if not isinstance(timestamp, int) or isinstance(timestamp, bool):
        raise ValueError("Expected an integer millisecond timestamp")
    return _EPOCH + timestamp * _MILLISECOND


def _milliseconds(value: datetime) -> int:
    if not isinstance(value, datetime):
        raise TypeError("Query times must be datetime values")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Query times must include a timezone")
    if value.microsecond % 1000:
        raise ValueError("Query times must have millisecond precision or coarser")
    return (value.astimezone(UTC) - _EPOCH) // _MILLISECOND


def _unique[T](items: Sequence[T], timestamp: Callable[[T], datetime]) -> list[T]:
    unique: dict[datetime, T] = {}
    previous = None
    for item in items:
        key = timestamp(item)
        if previous is not None and key < previous:
            raise InvalidMarketDataError("Exchange page timestamps are not ascending")
        if key in unique and unique[key] != item:
            raise InvalidMarketDataError("Exchange page contains conflicting duplicate timestamps")
        unique[key] = item
        previous = key
    return list(unique.values())


class CCXTProvider:
    """Implements MarketDataProvider for Binance spot or USDT linear perpetuals.

    Construction is network-free. Metadata is loaded lazily. A caller may
    inject a compatible fake CCXT client and sleeper for deterministic tests.
    Pages can contain an unfinished bar; the sync service applies its cutoff.
    """

    def __init__(
        self,
        market_type: MarketType,
        *,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
        timeout_ms: int = 30000,
        client: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(market_type, MarketType):
            raise TypeError("market_type must be a MarketType")
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if not math.isfinite(backoff_seconds) or backoff_seconds <= 0:
            raise ValueError("backoff_seconds must be finite and positive")
        if type(timeout_ms) is not int or timeout_ms <= 0:
            raise ValueError("timeout_ms must be a positive integer")
        self._market_type = market_type
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._closed = False
        self._markets: Mapping[str, Any] | None = None
        constructor = ccxt.binance if market_type is MarketType.SPOT else ccxt.binanceusdm
        self._client = client if client is not None else constructor()
        expected_id = "binance" if market_type is MarketType.SPOT else "binanceusdm"
        if self._client.id != expected_id:
            raise ValueError("Client does not match the selected Binance market type")
        self._client.enableRateLimit = True
        self._client.timeout = timeout_ms
        self._client.number = str
        self._client.options.update(
            {
                "defaultType": "spot" if market_type is MarketType.SPOT else "swap",
                "defaultSubType": "linear",
                "fetchMarkets": {"types": ["spot" if market_type is MarketType.SPOT else "linear"]},
                "fetchCurrencies": False,
                "fetchMargins": False,
                "maxRetriesOnFailure": 0,
            }
        )

    @property
    def exchange(self) -> str:
        return "binance"

    @property
    def market_type(self) -> MarketType:
        return self._market_type

    @property
    def supports_funding_history(self) -> bool:
        return (
            self.market_type is MarketType.PERPETUAL
            and self._client.has.get("fetchFundingRateHistory") is True
        )

    def _request[T](
        self, operation: Callable[[], T], *, unsupported: type[ProviderError] = ProviderError
    ) -> T:
        if self._closed:
            raise ProviderError("The market-data provider is closed")
        for attempt in range(self._max_retries + 1):
            try:
                return operation()
            except ccxt.BadSymbol as exc:
                raise UnsupportedMarketError(
                    "Binance does not recognize the requested market"
                ) from exc
            except ccxt.NotSupported as exc:
                raise unsupported("Binance does not support the requested data operation") from exc
            except ccxt.DDoSProtection as exc:
                raise ProviderError(
                    "Binance denied the request; automatic retries stopped"
                ) from exc
            except ccxt.NetworkError as exc:
                if attempt == self._max_retries:
                    raise TransientProviderError(
                        "Binance request failed after bounded retries"
                    ) from exc
                delay = min(self._backoff_seconds * (2 ** min(attempt, 10)), _MAX_RETRY_DELAY)
                if isinstance(exc, ccxt.RateLimitExceeded):
                    headers = self._client.last_response_headers or {}
                    retry_after = next(
                        (value for key, value in headers.items() if key.lower() == "retry-after"),
                        None,
                    )
                    if retry_after is not None:
                        try:
                            required = float(retry_after)
                        except (TypeError, ValueError):
                            required = math.inf
                        if not math.isfinite(required) or required > _MAX_RETRY_DELAY:
                            raise TransientProviderError(
                                "Binance requires a longer or unknown retry delay; retry later"
                            ) from exc
                        delay = max(delay, required)
                self._sleep(delay)
            except ccxt.BaseError as exc:
                raise ProviderError("Binance rejected the market-data request") from exc
        raise AssertionError("Unreachable retry state")

    def _load_markets(self) -> Mapping[str, Any]:
        if self._closed:
            raise ProviderError("The market-data provider is closed")
        if self._markets is None:
            markets = self._request(self._client.load_markets)
            if not isinstance(markets, Mapping):
                raise InvalidMarketDataError("Binance market metadata is not a mapping")
            self._markets = markets
        return self._markets

    def get_market(self, symbol: str) -> Market:
        raw = self._load_markets().get(symbol)
        if raw is None:
            raise UnsupportedMarketError("Exact unified symbol is absent from Binance metadata")
        if not isinstance(raw, Mapping):
            raise InvalidMarketDataError("Binance market metadata is malformed")
        if self.market_type is MarketType.SPOT:
            supported = raw.get("spot") is True and raw.get("contract") is not True
        else:
            supported = (
                raw.get("swap") is True
                and raw.get("linear") is True
                and raw.get("inverse") is False
                and raw.get("settle") == "USDT"
                and raw.get("quote") == "USDT"
                and raw.get("expiry") is None
            )
        if not supported or raw.get("symbol") != symbol:
            raise UnsupportedMarketError(
                "Symbol does not match the supported Binance contract type"
            )
        try:
            return Market(
                exchange=self.exchange,
                market_type=self.market_type,
                symbol=symbol,
                symbol_native=raw["id"],
                base_asset=raw["base"],
                quote_asset=raw["quote"],
                settle_asset=raw.get("settle")
                if self.market_type is MarketType.PERPETUAL
                else None,
                contract_size=_decimal(raw["contractSize"])
                if self.market_type is MarketType.PERPETUAL
                else None,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise InvalidMarketDataError("Binance market metadata is invalid") from exc

    def get_timeframes(self) -> frozenset[str]:
        self._load_markets()
        if self._client.has.get("fetchOHLCV") is not True:
            raise UnsupportedTimeframeError("Binance client does not support OHLCV history")
        return frozenset(self._client.timeframes or {})

    def _validate_market(self, market: Market) -> None:
        if market.exchange != self.exchange or market.market_type is not self.market_type:
            raise UnsupportedMarketError("Market belongs to a different exchange or market type")
        if self.get_market(market.symbol) != market:
            raise InvalidMarketDataError("Supplied market differs from verified exchange metadata")

    @staticmethod
    def _page_arguments(start: datetime, end: datetime, limit: int) -> tuple[int, int]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Binance page limit must be an integer between 1 and 1000")
        since, until = _milliseconds(start), _milliseconds(end)
        if since >= until:
            raise ValueError("Query start must be before end")
        return since, until - 1  # Binance's endTime is inclusive.

    @staticmethod
    def _validate_page(page: Any, limit: int) -> None:
        if not isinstance(page, (list, tuple)) or len(page) > limit:
            raise InvalidMarketDataError("Binance response is not a valid bounded page")

    def fetch_candles(
        self, market: Market, timeframe: str, *, start: datetime, end: datetime, limit: int
    ) -> Sequence[Candle]:
        requested = CandleRange(start, end, timeframe)
        since, until = self._page_arguments(requested.start, requested.end, limit)
        self._validate_market(market)
        if timeframe not in self.get_timeframes():
            raise UnsupportedTimeframeError("Binance does not provide the requested timeframe")
        page = self._request(
            lambda: self._client.fetch_ohlcv(
                market.symbol,
                timeframe=timeframe,
                since=since,
                limit=limit,
                params={"until": until, "paginate": False},
            ),
            unsupported=UnsupportedTimeframeError,
        )
        self._validate_page(page, limit)
        candles = []
        try:
            for raw in page:
                if not isinstance(raw, (list, tuple)) or len(raw) != 6:
                    raise ValueError("Expected six OHLCV fields")
                candle = Candle(_datetime(raw[0]), *(_decimal(value) for value in raw[1:]))
                if floor_to_bar(candle.open_time, timeframe) != candle.open_time:
                    raise ValueError("Unaligned candle time")
                candles.append(candle)
        except (TypeError, ValueError, InvalidOperation, OverflowError) as exc:
            raise InvalidMarketDataError("Binance returned invalid OHLCV data") from exc
        return [
            item
            for item in _unique(candles, lambda item: item.open_time)
            if requested.start <= item.open_time < requested.end
        ]

    def fetch_funding_rates(
        self, market: Market, *, start: datetime, end: datetime, limit: int
    ) -> Sequence[FundingRate]:
        since, until = self._page_arguments(start, end, limit)
        if self.market_type is not MarketType.PERPETUAL:
            raise FundingHistoryUnavailableError("Funding is not applicable to spot markets")
        self._validate_market(market)
        if not self.supports_funding_history:
            raise FundingHistoryUnavailableError("Binance client does not provide funding history")
        page = self._request(
            lambda: self._client.fetch_funding_rate_history(
                market.symbol,
                since=since,
                limit=limit,
                params={"until": until, "paginate": False},
            ),
            unsupported=FundingHistoryUnavailableError,
        )
        self._validate_page(page, limit)
        rates = []
        try:
            for raw in page:
                if not isinstance(raw, Mapping) or raw.get("symbol") != market.symbol:
                    raise ValueError("Funding event belongs to an unexpected symbol")
                info = raw.get("info") or {}
                if not isinstance(info, Mapping):
                    raise ValueError("Funding source metadata is malformed")
                mark = info.get("markPrice")
                rates.append(
                    FundingRate(
                        _datetime(raw["timestamp"]),
                        _decimal(raw["fundingRate"]),
                        source="binance:ccxt:fundingRateHistory",
                        # Historical Binance events may explicitly return markPrice="".
                        # Preserve absence, never invent a price or a zero funding rate.
                        mark_price=None if mark in (None, "") else _decimal(mark),
                    )
                )
        except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError) as exc:
            raise InvalidMarketDataError("Binance returned invalid funding data") from exc
        return [
            item
            for item in _unique(rates, lambda item: item.funding_time)
            if start <= item.funding_time < end
        ]

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._client.close()
