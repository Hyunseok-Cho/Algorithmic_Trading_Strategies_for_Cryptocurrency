"""PostgreSQL persistence schema; importing this module never connects to a DB."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from trading_lab.domain.enums import MarketType, PositionSide


class Base(DeclarativeBase):
    """Stable constraint names make subsequent Alembic migrations reviewable."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def _enum(enum_type: type[StrEnum]) -> Enum:
    # Persist lowercase values ("spot"), not Python member names ("SPOT").
    return Enum(
        enum_type,
        values_callable=lambda members: [member.value for member in members],
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        name=enum_type.__name__.lower(),
    )


def _finite(*columns: str) -> CheckConstraint:
    # PostgreSQL NUMERIC permits NaN/Infinity; positivity checks alone miss NaN.
    return CheckConstraint(
        " AND ".join(
            f"({column} > '-Infinity'::numeric AND {column} < 'Infinity'::numeric)"
            for column in columns
        ),
        name="numeric_finite",
    )


class MarketRow(Base):
    __tablename__ = "markets"
    __table_args__ = (
        UniqueConstraint("exchange", "market_type", "symbol_unified"),
        CheckConstraint(
            "(market_type = 'spot' AND settle_asset IS NULL AND contract_size IS NULL) OR "
            "(market_type = 'perpetual' AND quote_asset = 'USDT' "
            "AND settle_asset IS NOT NULL AND settle_asset = 'USDT' "
            "AND contract_size IS NOT NULL AND contract_size > 0)",
            name="market_contract",
        ),
        _finite("contract_size"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(64))
    market_type: Mapped[MarketType] = mapped_column(_enum(MarketType))
    symbol_unified: Mapped[str] = mapped_column(String(128))
    symbol_native: Mapped[str] = mapped_column(String(128))
    base_asset: Mapped[str] = mapped_column(String(64))
    quote_asset: Mapped[str] = mapped_column(String(64))
    settle_asset: Mapped[str | None] = mapped_column(String(64))
    contract_size: Mapped[Decimal | None] = mapped_column(Numeric())
    # NULL until a provider establishes actual availability, not just first saved data.
    first_available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CandleRow(Base):
    """The composite primary key also indexes market/timeframe/range queries."""

    __tablename__ = "candles"
    __table_args__ = (
        CheckConstraint(
            "open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0 "
            "AND low <= open AND low <= close AND high >= open AND high >= close",
            name="valid_ohlcv",
        ),
        _finite("open", "high", "low", "close", "volume"),
    )

    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(16), primary_key=True)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric())
    high: Mapped[Decimal] = mapped_column(Numeric())
    low: Mapped[Decimal] = mapped_column(Numeric())
    close: Mapped[Decimal] = mapped_column(Numeric())
    volume: Mapped[Decimal] = mapped_column(Numeric())
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FundingRateRow(Base):
    __tablename__ = "funding_rates"
    __table_args__ = (
        CheckConstraint("mark_price IS NULL OR mark_price > 0", name="positive_mark_price"),
        _finite("funding_rate", "mark_price"),
    )

    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), primary_key=True)
    funding_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    funding_rate: Mapped[Decimal] = mapped_column(Numeric())
    mark_price: Mapped[Decimal | None] = mapped_column(Numeric())
    source: Mapped[str] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SyncJobRow(Base):
    """A committed page advances the cursor; a failed job remains inspectable."""

    __tablename__ = "sync_jobs"
    __table_args__ = (
        CheckConstraint("dataset IN ('candles', 'funding_rates')", name="dataset"),
        CheckConstraint(
            "(dataset = 'candles' AND timeframe IS NOT NULL) OR "
            "(dataset = 'funding_rates' AND timeframe IS NULL)",
            name="dataset_timeframe",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partial', 'failed')", name="status"
        ),
        CheckConstraint("requested_start < requested_end", name="requested_range"),
        CheckConstraint("inserted_count >= 0 AND updated_count >= 0", name="counts"),
        Index("ix_sync_jobs_market_dataset_started", "market_id", "dataset", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"))
    dataset: Mapped[str] = mapped_column(String(32))
    # NULL for funding, which is event data rather than a fixed candle interval.
    timeframe: Mapped[str | None] = mapped_column(String(16))
    requested_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requested_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_committed_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    inserted_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    updated_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DataCoverageRow(Base):
    """Latest checked candle range; MAX(open_time) alone never means complete.

    missing_ranges contains UTC [start, end) intervals within the checked range.
    An absent row means not checked, not complete. Funding coverage is recorded
    in funding sync job details because its event schedule may vary.
    """

    __tablename__ = "data_coverage"
    __table_args__ = (
        CheckConstraint("checked_start < checked_end", name="checked_range"),
        CheckConstraint("candle_count >= 0", name="candle_count"),
        CheckConstraint(
            "first_open_time IS NULL OR last_open_time IS NULL OR first_open_time <= last_open_time",
            name="observed_range",
        ),
    )

    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(16), primary_key=True)
    checked_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    checked_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candle_count: Mapped[int] = mapped_column(BigInteger)
    missing_ranges: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    warnings: Mapped[list[str]] = mapped_column(JSONB)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BacktestRunRow(Base):
    """Reproducible request and results, including failed report generation.

    Initial policy: equity curve and daily statistics live in result_payload
    and report files; completed trades also have dedicated queryable rows.
    JSON payloads must be JSON-compatible, with Decimal encoded as strings.
    Replace JSON values as a whole: in-place mutations are not ORM-tracked.
    """

    __tablename__ = "backtest_runs"
    __table_args__ = (
        CheckConstraint("start_time < end_time", name="requested_range"),
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="status"),
        CheckConstraint(
            "report_status IN ('pending', 'completed', 'failed')", name="report_status"
        ),
        Index("ix_backtest_runs_strategy_created", "strategy_id", "created_at"),
        Index("ix_backtest_runs_market_created", "market_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"))
    strategy_id: Mapped[str] = mapped_column(String(64))
    timeframe: Mapped[str] = mapped_column(String(16))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    data_provenance: Mapped[dict[str, Any]] = mapped_column(JSONB)
    model_version: Mapped[str] = mapped_column(String(64))
    code_revision: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    warnings: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    assumptions: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)
    report_status: Mapped[str] = mapped_column(String(16), server_default="pending")
    report_path: Mapped[str | None] = mapped_column(Text)
    report_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BacktestTradeRow(Base):
    """Completed round trips. Funding is signed cash flow: receipt is positive.

    Side is stored per trade, so future hedge-mode trades can remain distinct.
    This schema does not imply that the initial engine supports hedge mode.
    """

    __tablename__ = "backtest_trades"
    __table_args__ = (
        CheckConstraint("trade_number > 0", name="trade_number"),
        CheckConstraint("exit_time >= entry_time", name="trade_times"),
        CheckConstraint(
            "entry_price > 0 AND exit_price > 0 AND quantity > 0 AND fees >= 0",
            name="trade_amounts",
        ),
        CheckConstraint("net_pnl = gross_pnl - fees + funding", name="net_pnl"),
        _finite(
            "entry_price",
            "exit_price",
            "quantity",
            "gross_pnl",
            "fees",
            "funding",
            "net_pnl",
            "net_return_pct",
        ),
    )

    run_id: Mapped[UUID] = mapped_column(ForeignKey("backtest_runs.id"), primary_key=True)
    trade_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    position_side: Mapped[PositionSide] = mapped_column(_enum(PositionSide))
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[Decimal] = mapped_column(Numeric())
    exit_price: Mapped[Decimal] = mapped_column(Numeric())
    quantity: Mapped[Decimal] = mapped_column(Numeric())
    gross_pnl: Mapped[Decimal] = mapped_column(Numeric())
    fees: Mapped[Decimal] = mapped_column(Numeric())
    funding: Mapped[Decimal] = mapped_column(Numeric())
    net_pnl: Mapped[Decimal] = mapped_column(Numeric())
    net_return_pct: Mapped[Decimal | None] = mapped_column(Numeric())
    exit_reason: Mapped[str] = mapped_column(String(64))
    liquidated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
