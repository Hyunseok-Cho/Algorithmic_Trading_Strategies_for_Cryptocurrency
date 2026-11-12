"""Market-data contracts; implementations need not inherit from these protocols.

All datetime arguments must be timezone-aware. Ranges are UTC [start, end).
These declarations contain no network, SQL, pandas or trading logic.
"""

from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import NamedTuple, Protocol

from trading_lab.domain.enums import MarketType
from trading_lab.domain.models import Candle, FundingRate, Market


class WriteCounts(NamedTuple):
    """Non-negative counts of inserted and changed rows; unchanged rows are excluded.

    Counts describe writes in the current transaction, not a successful commit.
    A repository must not count every submitted duplicate as a new insert.
    """

    inserted: int
    updated: int


class MarketDataProvider(Protocol):
    """One exchange/market-type client, created and closed by its caller.

    The adapter verifies market metadata and capabilities, normalizes decimal
    values and volume units, and handles bounded transient-error retries and
    rate limits. Permanent failures and unsupported operations must raise;
    they must never masquerade as an empty successful response.
    """

    @property
    def exchange(self) -> str: ...

    @property
    def market_type(self) -> MarketType: ...

    @property
    def supports_funding_history(self) -> bool: ...

    def get_market(self, symbol: str) -> Market:
        """Resolve an exact unified symbol and reject a different market type."""
        ...

    def get_timeframes(self) -> frozenset[str]:
        """Return supported OHLCV intervals; do not assume every exchange supports 3h."""
        ...

    def fetch_candles(
        self,
        market: Market,
        timeframe: str,
        *,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> Sequence[Candle]:
        """Fetch at most one page within [start, end), sorted and deduplicated.

        limit must be positive and respect exchange endpoint limits. A page
        can include an uncompleted candle: the service excludes it using its
        captured cutoff time. Empty/short pages do not prove full coverage
        or establish a market's actual first historical availability.
        """
        ...

    def fetch_funding_rates(
        self,
        market: Market,
        *,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> Sequence[FundingRate]:
        """Fetch one ordered, deduplicated page of observed perpetual events.

        Reject spot and unsupported history access. Do not fabricate missing
        events, substitute zero rates or assume a fixed funding interval.
        """
        ...

    def close(self) -> None:
        """Release adapter resources; the caller closes even after failures."""
        ...


class MarketDataReader(Protocol):
    """DB-only reads: backtesting receives this contract, never a provider.

    Iterators yield ascending timestamps and must be consumed while their
    caller-owned session is open. Reads never trigger exchange requests.
    """

    def find_market(self, exchange: str, market_type: MarketType, symbol: str) -> Market | None:
        """Return saved market metadata; None means not registered locally."""
        ...

    def latest_candle_time(
        self, market: Market, timeframe: str, *, before: datetime
    ) -> datetime | None:
        """Return the latest stored open_time < before, not a coverage guarantee."""
        ...

    def iter_candle_times(
        self, market: Market, timeframe: str, *, start: datetime, end: datetime
    ) -> Iterator[datetime]:
        """Stream timestamps for gap inspection without loading all OHLCV fields."""
        ...

    def iter_candles(
        self, market: Market, timeframe: str, *, start: datetime, end: datetime
    ) -> Iterator[Candle]: ...

    def latest_funding_time(self, market: Market, *, before: datetime) -> datetime | None: ...

    def iter_funding_rates(
        self, market: Market, *, start: datetime, end: datetime
    ) -> Iterator[FundingRate]: ...


class MarketDataRepository(MarketDataReader, Protocol):
    """Reads plus idempotent writes within a caller-owned transaction.

    Repositories never commit, roll back, close a session or call an exchange.
    A service must save a page and its sync-job cursor in one transaction.
    Sync-job and coverage persistence contracts are defined separately.
    """

    def save_market(self, market: Market) -> None:
        """Insert/update verified metadata, unique by exchange/type/unified symbol."""
        ...

    def upsert_candles(
        self, market: Market, timeframe: str, candles: Sequence[Candle]
    ) -> WriteCounts:
        """Upsert by market/timeframe/open_time; reject conflicting in-page duplicates."""
        ...

    def upsert_funding_rates(self, market: Market, rates: Sequence[FundingRate]) -> WriteCounts:
        """Upsert by market/funding_time; reject spot and conflicting in-page duplicates."""
        ...
