"""PostgreSQL market-data storage within a caller-owned SQLAlchemy session."""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Table, cast, column, func, or_, select, update, values
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from trading_lab.domain.enums import MarketType
from trading_lab.domain.exceptions import DataCoverageError, InvalidMarketDataError, RepositoryError
from trading_lab.domain.interfaces import WriteCounts
from trading_lab.domain.models import Candle, FundingRate, Market
from trading_lab.domain.timeframes import CandleRange, floor_to_bar, timeframe_delta
from trading_lab.infrastructure.database.models import CandleRow, FundingRateRow, MarketRow

_BATCH_SIZE = 500


@contextmanager
def _database_errors() -> Iterator[None]:
    try:
        yield
    except DBAPIError as exc:
        raise RepositoryError("Market-data database operation failed") from exc


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Database query times must be datetime values")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Database query times must include a timezone")
    return value.astimezone(UTC)


def _funding_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    start, end = _utc(start), _utc(end)
    if start >= end:
        raise ValueError("Funding query start must be before end")
    return start, end


class PostgresMarketDataRepository:
    """Implements MarketDataRepository structurally, without inheriting its Protocol.

    Only flushed/committed rows are visible to Core queries. The repository
    never commits, closes the session, changes isolation or calls an exchange.
    Consume streaming iterators within the transaction that created them.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _identity(exchange: str, market_type: MarketType, symbol: str) -> tuple:
        if not isinstance(market_type, MarketType):
            raise TypeError("market_type must be a MarketType")
        return (
            MarketRow.exchange == exchange,
            MarketRow.market_type == market_type,
            MarketRow.symbol_unified == symbol,
        )

    def _market_id(self, market: Market) -> int:
        statement = select(MarketRow.id).where(
            *self._identity(market.exchange, market.market_type, market.symbol)
        )
        with _database_errors():
            market_id = self._session.execute(statement).scalar_one_or_none()
        if market_id is None:
            raise DataCoverageError("Requested market is not registered in the local database")
        return market_id

    def find_market(self, exchange: str, market_type: MarketType, symbol: str) -> Market | None:
        statement = select(MarketRow.__table__).where(
            *self._identity(exchange, market_type, symbol)
        )
        with _database_errors():
            row = self._session.execute(statement).mappings().one_or_none()
        if row is None:
            return None
        try:
            return Market(
                exchange=row["exchange"],
                market_type=row["market_type"],
                symbol=row["symbol_unified"],
                symbol_native=row["symbol_native"],
                base_asset=row["base_asset"],
                quote_asset=row["quote_asset"],
                settle_asset=row["settle_asset"],
                contract_size=row["contract_size"],
            )
        except (TypeError, ValueError) as exc:
            raise InvalidMarketDataError("Stored market metadata is invalid") from exc

    def save_market(self, market: Market) -> None:
        table = MarketRow.__table__
        statement = insert(table).values(
            exchange=market.exchange,
            market_type=market.market_type,
            symbol_unified=market.symbol,
            symbol_native=market.symbol_native,
            base_asset=market.base_asset,
            quote_asset=market.quote_asset,
            settle_asset=market.settle_asset,
            contract_size=market.contract_size,
        )
        metadata_fields = (
            "symbol_native",
            "base_asset",
            "quote_asset",
            "settle_asset",
            "contract_size",
        )
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.exchange, table.c.market_type, table.c.symbol_unified],
            set_={name: statement.excluded[name] for name in metadata_fields},
            where=or_(
                *(
                    table.c[name].is_distinct_from(statement.excluded[name])
                    for name in metadata_fields
                )
            ),
        )
        # No first_available_at inference from a local MIN(open_time).
        with _database_errors():
            self._session.execute(statement).close()

    def latest_candle_time(
        self, market: Market, timeframe: str, *, before: datetime
    ) -> datetime | None:
        timeframe_delta(timeframe)
        before = _utc(before)
        statement = select(func.max(CandleRow.open_time)).where(
            CandleRow.market_id == self._market_id(market),
            CandleRow.timeframe == timeframe,
            CandleRow.open_time < before,
        )
        with _database_errors():
            return self._session.execute(statement).scalar_one()

    def iter_candle_times(
        self, market: Market, timeframe: str, *, start: datetime, end: datetime
    ) -> Iterator[datetime]:
        requested = CandleRange(start, end, timeframe)
        statement = (
            select(CandleRow.open_time)
            .where(
                CandleRow.market_id == self._market_id(market),
                CandleRow.timeframe == timeframe,
                CandleRow.open_time >= requested.start,
                CandleRow.open_time < requested.end,
            )
            .order_by(CandleRow.open_time)
        )
        for row in self._stream(statement):
            yield _utc(row["open_time"])

    def iter_candles(
        self, market: Market, timeframe: str, *, start: datetime, end: datetime
    ) -> Iterator[Candle]:
        requested = CandleRange(start, end, timeframe)
        statement = (
            select(CandleRow.__table__)
            .where(
                CandleRow.market_id == self._market_id(market),
                CandleRow.timeframe == timeframe,
                CandleRow.open_time >= requested.start,
                CandleRow.open_time < requested.end,
            )
            .order_by(CandleRow.open_time)
        )
        for row in self._stream(statement):
            try:
                yield Candle(
                    **{
                        name: row[name]
                        for name in ("open_time", "open", "high", "low", "close", "volume")
                    }
                )
            except (TypeError, ValueError) as exc:
                raise InvalidMarketDataError("Stored candle data is invalid") from exc

    @staticmethod
    def _require_perpetual(market: Market) -> None:
        if market.market_type is not MarketType.PERPETUAL:
            raise ValueError("Funding data is only applicable to perpetual markets")

    def latest_funding_time(self, market: Market, *, before: datetime) -> datetime | None:
        self._require_perpetual(market)
        before = _utc(before)
        statement = select(func.max(FundingRateRow.funding_time)).where(
            FundingRateRow.market_id == self._market_id(market),
            FundingRateRow.funding_time < before,
        )
        with _database_errors():
            return self._session.execute(statement).scalar_one()

    def iter_funding_rates(
        self, market: Market, *, start: datetime, end: datetime
    ) -> Iterator[FundingRate]:
        self._require_perpetual(market)
        start, end = _funding_range(start, end)
        statement = (
            select(FundingRateRow.__table__)
            .where(
                FundingRateRow.market_id == self._market_id(market),
                FundingRateRow.funding_time >= start,
                FundingRateRow.funding_time < end,
            )
            .order_by(FundingRateRow.funding_time)
        )
        for row in self._stream(statement):
            try:
                yield FundingRate(
                    row["funding_time"], row["funding_rate"], row["source"], row["mark_price"]
                )
            except (TypeError, ValueError) as exc:
                raise InvalidMarketDataError("Stored funding data is invalid") from exc

    def _stream(self, statement: Any) -> Iterator[Mapping[str, Any]]:
        with _database_errors():
            result = self._session.execute(statement.execution_options(yield_per=1000))
            try:
                yield from result.mappings()
            finally:
                result.close()

    def upsert_candles(
        self, market: Market, timeframe: str, candles: Sequence[Candle]
    ) -> WriteCounts:
        timeframe_delta(timeframe)
        unique: dict[datetime, Candle] = {}
        for candle in candles:
            if not isinstance(candle, Candle):
                raise TypeError("candles must contain Candle objects")
            if floor_to_bar(candle.open_time, timeframe) != candle.open_time:
                raise InvalidMarketDataError("Candle time is not aligned to its UTC timeframe")
            if candle.open_time in unique and unique[candle.open_time] != candle:
                raise InvalidMarketDataError("Conflicting candles share the same open time")
            unique[candle.open_time] = candle
        if not unique:
            return WriteCounts(0, 0)
        market_id = self._market_id(market)
        rows = [
            dict(
                market_id=market_id,
                timeframe=timeframe,
                open_time=candle.open_time,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            )
            for candle in sorted(unique.values(), key=lambda item: item.open_time)
        ]
        return self._write_rows(
            CandleRow.__table__,
            rows,
            ("market_id", "timeframe", "open_time"),
            ("open", "high", "low", "close", "volume"),
        )

    def upsert_funding_rates(self, market: Market, rates: Sequence[FundingRate]) -> WriteCounts:
        self._require_perpetual(market)
        unique: dict[datetime, FundingRate] = {}
        for rate in rates:
            if not isinstance(rate, FundingRate):
                raise TypeError("rates must contain FundingRate objects")
            if rate.funding_time in unique and unique[rate.funding_time] != rate:
                raise InvalidMarketDataError("Conflicting funding events share the same time")
            unique[rate.funding_time] = rate
        if not unique:
            return WriteCounts(0, 0)
        market_id = self._market_id(market)
        rows = [
            dict(
                market_id=market_id,
                funding_time=rate.funding_time,
                funding_rate=rate.rate,
                mark_price=rate.mark_price,
                source=rate.source,
            )
            for rate in sorted(unique.values(), key=lambda item: item.funding_time)
        ]
        return self._write_rows(
            FundingRateRow.__table__,
            rows,
            ("market_id", "funding_time"),
            ("funding_rate", "mark_price", "source"),
        )

    def _write_rows(
        self,
        table: Table,
        rows: list[dict[str, Any]],
        keys: tuple[str, ...],
        fields: tuple[str, ...],
    ) -> WriteCounts:
        """Count actual inserts and changes without relying on PostgreSQL xmax.

        Insert missing keys with ON CONFLICT DO NOTHING, then UPDATE FROM VALUES
        only where payload differs (NULL-safe). Unchanged repeats do not change
        ingested_at. All chunks remain within the caller's single transaction.
        """
        inserted = updated = 0
        names = (*keys, *fields)
        with _database_errors():
            for offset in range(0, len(rows), _BATCH_SIZE):
                batch = rows[offset : offset + _BATCH_SIZE]
                statement = (
                    insert(table)
                    .values(batch)
                    .on_conflict_do_nothing(index_elements=[table.c[name] for name in keys])
                    .returning(table.c[keys[-1]])
                )
                result = self._session.execute(statement)
                try:
                    inserted += sum(1 for _ in result)
                finally:
                    result.close()

                incoming = values(
                    *(column(name, table.c[name].type) for name in names), name="incoming"
                ).data(
                    [tuple(cast(row[name], table.c[name].type) for name in names) for row in batch]
                )
                changed = or_(
                    *(table.c[name].is_distinct_from(incoming.c[name]) for name in fields)
                )
                statement = (
                    update(table)
                    .where(
                        *(table.c[name] == incoming.c[name] for name in keys),
                        changed,
                    )
                    .values(**{name: incoming.c[name] for name in fields}, ingested_at=func.now())
                    .returning(table.c[keys[-1]])
                )
                result = self._session.execute(statement)
                try:
                    updated += sum(1 for _ in result)
                finally:
                    result.close()
        return WriteCounts(inserted, updated)
