"""Framework-independent validated requests and serializable results."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_lab import MODEL_VERSION
from trading_lab.domain.enums import (
    DirectionMode,
    FundingMode,
    MarginMode,
    MarketType,
    PositionMode,
)
from trading_lab.domain.timeframes import CandleRange


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class BacktestRequest(Record):
    exchange: Literal["binance"] = "binance"
    market_type: MarketType = MarketType.SPOT
    symbol: str = Field(min_length=1)
    timeframe: str = "1h"
    start_time: AwareDatetime
    end_time: AwareDatetime
    strategy_id: str = Field(min_length=1)
    # Missing in historical payloads/configs: preserve their original v1 identity.
    strategy_version: Literal["v1", "v2", "v3", "v4", "v5", "v6"] = "v1"
    strategy_parameters: dict[str, Any] = Field(default_factory=dict)
    initial_capital: Decimal = Field(gt=0, max_digits=30, decimal_places=12)
    # Historical naming: this is the account/quote currency, not BTC in BTC/USDT.
    base_currency: Literal["USDT"] = "USDT"
    position_sizing: Literal["equity_percent"] = "equity_percent"
    allocation_pct: Decimal = Field(default=Decimal("100"), gt=0, le=100)
    direction_mode: DirectionMode = DirectionMode.LONG_ONLY
    leverage: Decimal = Field(default=Decimal("1"), ge=1, le=125)
    fee_rate_open: Decimal = Field(ge=0, lt=1)
    fee_rate_close: Decimal = Field(ge=0, lt=1)
    slippage_bps: Decimal = Field(ge=0, lt=10000)
    warmup_bars: int = Field(default=0, ge=0, strict=True)
    execution_rule: Literal["next_bar_open"] = "next_bar_open"
    position_mode: PositionMode = PositionMode.ONE_WAY
    margin_mode: MarginMode = MarginMode.ISOLATED
    funding_mode: FundingMode = FundingMode.STRICT
    expected_funding_times: tuple[AwareDatetime, ...] | None = None
    funding_schedule_source: str | None = None
    maintenance_margin_rate: Decimal = Field(default=Decimal("0.005"), ge=0, lt=1)
    liquidation_fee_rate: Decimal = Field(default=Decimal("0.005"), ge=0, lt=1)
    close_open_position_at_end: bool = True
    stop_loss_pct: Decimal | None = Field(default=None, gt=0, lt=100)
    take_profit_pct: Decimal | None = Field(default=None, gt=0, lt=100)

    @field_validator("start_time", "end_time")
    @classmethod
    def utc_times(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_validator("symbol", "strategy_id")
    @classmethod
    def clean_names(cls, value: str) -> str:
        if value != value.strip() or not value:
            raise ValueError("Names must be non-empty without surrounding whitespace")
        return value

    @field_validator("funding_schedule_source")
    @classmethod
    def nonblank_schedule_source(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Funding schedule source must not be blank")
        return value

    @model_validator(mode="after")
    def validate_experiment(self):
        CandleRange(self.start_time, self.end_time, self.timeframe)
        if self.strategy_id == "rsi" and self.strategy_version == "v2":
            if self.stop_loss_pct is None or self.take_profit_pct is not None:
                raise ValueError("RSI v2 requires stop_loss_pct and forbids take_profit_pct")
        if self.strategy_id == "rsi" and self.strategy_version == "v3":
            if self.stop_loss_pct is None or self.take_profit_pct is None:
                raise ValueError("RSI v3 requires stop_loss_pct and take_profit_pct")
        if self.position_mode is PositionMode.HEDGE:
            raise ValueError("hedge is reserved; this engine currently supports one_way only")
        if self.market_type is MarketType.SPOT:
            if self.direction_mode is not DirectionMode.LONG_ONLY or self.leverage != 1:
                raise ValueError("Spot requires long_only and leverage=1")
            if ":" in self.symbol or not self.symbol.endswith("/USDT"):
                raise ValueError("Spot requires a USDT quote unified symbol, e.g. BTC/USDT")
        elif not self.symbol.endswith("/USDT:USDT"):
            raise ValueError("Perpetual requires a USDT linear symbol, e.g. BTC/USDT:USDT")
        if self.maintenance_margin_rate + self.liquidation_fee_rate >= 1:
            raise ValueError("Maintenance plus liquidation fee rate must be below 1")
        if (
            self.market_type is MarketType.PERPETUAL
            and self.leverage * (self.maintenance_margin_rate + self.liquidation_fee_rate) >= 1
        ):
            raise ValueError("Configured leverage leaves no maintenance margin safety buffer")
        if self.expected_funding_times is not None:
            times = tuple(value.astimezone(UTC) for value in self.expected_funding_times)
            if tuple(sorted(set(times))) != times:
                raise ValueError("Expected funding times must be unique and ascending")
            if any(not self.start_time <= value < self.end_time for value in times):
                raise ValueError("Expected funding events must lie inside [start, end)")
            object.__setattr__(self, "expected_funding_times", times)
        return self


class Trade(Record):
    trade_number: int
    position_side: Literal["long", "short"]
    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    capital_committed: Decimal
    price_pnl: Decimal
    limited_loss_adjustment: Decimal
    gross_pnl: Decimal
    fees: Decimal
    funding: Decimal
    net_pnl: Decimal
    net_return_pct: Decimal | None
    duration_seconds: float
    exit_reason: str
    liquidated: bool


class EquityPoint(Record):
    time: datetime
    equity: Decimal
    cash: Decimal
    margin: Decimal
    unrealized_pnl: Decimal


class BacktestResult(Record):
    run_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model_version: str = MODEL_VERSION
    code_revision: str | None = None
    request: BacktestRequest
    summary: dict[str, Any]
    trades: tuple[Trade, ...]
    equity_curve: tuple[EquityPoint, ...]
    daily_statistics: tuple[dict[str, Any], ...]
    data_quality: dict[str, Any]
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]
    order_count: int

    @field_validator("summary", mode="before")
    @classmethod
    def restore_summary_decimals(cls, value):
        # JSON stores exact Decimal strings. Re-exported DB runs must retain
        # numeric Excel cells instead of turning monetary amounts into text.
        fields = {
            "initial_equity",
            "ending_equity",
            "net_pnl",
            "total_return_pct",
            "realized_pnl",
            "unrealized_pnl",
            "gross_pnl",
            "uncapped_price_pnl",
            "limited_loss_adjustment",
            "total_fees",
            "total_funding",
            "settlement_rounding_residual",
            "win_rate_pct",
            "total_profit",
            "total_loss",
            "best_profit",
            "worst_loss",
            "average_profit",
            "average_loss",
            "median_trade_pnl",
            "average_trade_return_pct",
            "average_winning_return_pct",
            "average_losing_return_pct",
            "profit_factor",
            "expectancy",
            "max_drawdown",
            "max_drawdown_pct",
            "buy_and_hold_ending_equity",
            "buy_and_hold_return_pct",
            "excess_return_pct",
        }
        return {
            key: Decimal(item) if key in fields and isinstance(item, str) else item
            for key, item in value.items()
        }

    @field_validator("daily_statistics", mode="before")
    @classmethod
    def restore_daily_decimals(cls, value):
        fields = {"opening_equity", "ending_equity", "pnl", "return_pct"}
        return tuple(
            {
                key: Decimal(item) if key in fields and isinstance(item, str) else item
                for key, item in row.items()
            }
            for row in value
        )


class SyncResult(Record):
    job_id: UUID | None
    status: str
    inserted_count: int = 0
    updated_count: int = 0
    candle_count: int | None = None
    missing_ranges: tuple[dict[str, str], ...] = ()
    warnings: tuple[str, ...] = ()
