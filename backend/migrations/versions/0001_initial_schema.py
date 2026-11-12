"""Create the initial PostgreSQL research schema.

Revision ID: 0001_initial_schema
Revises: None

This revision is a schema snapshot; do not import application models here.
Downgrade drops all research tables and their data; it is never automatic.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "markets",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("exchange", sa.String(length=64), nullable=False),
        sa.Column(
            "market_type",
            sa.Enum(
                "spot", "perpetual", name="markettype", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("symbol_unified", sa.String(length=128), nullable=False),
        sa.Column("symbol_native", sa.String(length=128), nullable=False),
        sa.Column("base_asset", sa.String(length=64), nullable=False),
        sa.Column("quote_asset", sa.String(length=64), nullable=False),
        sa.Column("settle_asset", sa.String(length=64), nullable=True),
        sa.Column("contract_size", sa.Numeric(), nullable=True),
        sa.Column("first_available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(contract_size > '-Infinity'::numeric AND contract_size < 'Infinity'::numeric)",
            name=op.f("ck_markets_numeric_finite"),
        ),
        sa.CheckConstraint(
            "(market_type = 'spot' AND settle_asset IS NULL AND contract_size IS NULL) OR (market_type = 'perpetual' AND quote_asset = 'USDT' AND settle_asset IS NOT NULL AND settle_asset = 'USDT' AND contract_size IS NOT NULL AND contract_size > 0)",
            name=op.f("ck_markets_market_contract"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_markets")),
        sa.UniqueConstraint(
            "exchange", "market_type", "symbol_unified", name=op.f("uq_markets_exchange")
        ),
    )
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("data_provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("code_revision", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column(
            "summary", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "result_payload",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("report_status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("report_path", sa.Text(), nullable=True),
        sa.Column("report_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "report_status IN ('pending', 'completed', 'failed')",
            name=op.f("ck_backtest_runs_report_status"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=op.f("ck_backtest_runs_status"),
        ),
        sa.CheckConstraint("start_time < end_time", name=op.f("ck_backtest_runs_requested_range")),
        sa.ForeignKeyConstraint(
            ["market_id"], ["markets.id"], name=op.f("fk_backtest_runs_market_id_markets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_runs")),
    )
    op.create_index(
        "ix_backtest_runs_market_created",
        "backtest_runs",
        ["market_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_backtest_runs_strategy_created",
        "backtest_runs",
        ["strategy_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "candles",
        sa.Column("market_id", sa.BigInteger(), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(), nullable=False),
        sa.Column("high", sa.Numeric(), nullable=False),
        sa.Column("low", sa.Numeric(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("volume", sa.Numeric(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(open > '-Infinity'::numeric AND open < 'Infinity'::numeric) AND (high > '-Infinity'::numeric AND high < 'Infinity'::numeric) AND (low > '-Infinity'::numeric AND low < 'Infinity'::numeric) AND (close > '-Infinity'::numeric AND close < 'Infinity'::numeric) AND (volume > '-Infinity'::numeric AND volume < 'Infinity'::numeric)",
            name=op.f("ck_candles_numeric_finite"),
        ),
        sa.CheckConstraint(
            "open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0 AND low <= open AND low <= close AND high >= open AND high >= close",
            name=op.f("ck_candles_valid_ohlcv"),
        ),
        sa.ForeignKeyConstraint(
            ["market_id"], ["markets.id"], name=op.f("fk_candles_market_id_markets")
        ),
        sa.PrimaryKeyConstraint("market_id", "timeframe", "open_time", name=op.f("pk_candles")),
    )
    op.create_table(
        "data_coverage",
        sa.Column("market_id", sa.BigInteger(), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("checked_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_open_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_open_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candle_count", sa.BigInteger(), nullable=False),
        sa.Column("missing_ranges", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("candle_count >= 0", name=op.f("ck_data_coverage_candle_count")),
        sa.CheckConstraint(
            "checked_start < checked_end", name=op.f("ck_data_coverage_checked_range")
        ),
        sa.CheckConstraint(
            "first_open_time IS NULL OR last_open_time IS NULL OR first_open_time <= last_open_time",
            name=op.f("ck_data_coverage_observed_range"),
        ),
        sa.ForeignKeyConstraint(
            ["market_id"], ["markets.id"], name=op.f("fk_data_coverage_market_id_markets")
        ),
        sa.PrimaryKeyConstraint("market_id", "timeframe", name=op.f("pk_data_coverage")),
    )
    op.create_table(
        "funding_rates",
        sa.Column("market_id", sa.BigInteger(), nullable=False),
        sa.Column("funding_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("funding_rate", sa.Numeric(), nullable=False),
        sa.Column("mark_price", sa.Numeric(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(funding_rate > '-Infinity'::numeric AND funding_rate < 'Infinity'::numeric) AND (mark_price > '-Infinity'::numeric AND mark_price < 'Infinity'::numeric)",
            name=op.f("ck_funding_rates_numeric_finite"),
        ),
        sa.CheckConstraint(
            "mark_price IS NULL OR mark_price > 0",
            name=op.f("ck_funding_rates_positive_mark_price"),
        ),
        sa.ForeignKeyConstraint(
            ["market_id"], ["markets.id"], name=op.f("fk_funding_rates_market_id_markets")
        ),
        sa.PrimaryKeyConstraint("market_id", "funding_time", name=op.f("pk_funding_rates")),
    )
    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=True),
        sa.Column("requested_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_committed_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("inserted_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("updated_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(dataset = 'candles' AND timeframe IS NOT NULL) OR (dataset = 'funding_rates' AND timeframe IS NULL)",
            name=op.f("ck_sync_jobs_dataset_timeframe"),
        ),
        sa.CheckConstraint(
            "dataset IN ('candles', 'funding_rates')", name=op.f("ck_sync_jobs_dataset")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partial', 'failed')",
            name=op.f("ck_sync_jobs_status"),
        ),
        sa.CheckConstraint(
            "inserted_count >= 0 AND updated_count >= 0", name=op.f("ck_sync_jobs_counts")
        ),
        sa.CheckConstraint(
            "requested_start < requested_end", name=op.f("ck_sync_jobs_requested_range")
        ),
        sa.ForeignKeyConstraint(
            ["market_id"], ["markets.id"], name=op.f("fk_sync_jobs_market_id_markets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_jobs")),
    )
    op.create_index(
        "ix_sync_jobs_market_dataset_started",
        "sync_jobs",
        ["market_id", "dataset", "started_at"],
        unique=False,
    )
    op.create_table(
        "backtest_trades",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("trade_number", sa.Integer(), nullable=False),
        sa.Column(
            "position_side",
            sa.Enum(
                "long", "short", name="positionside", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(), nullable=False),
        sa.Column("exit_price", sa.Numeric(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("gross_pnl", sa.Numeric(), nullable=False),
        sa.Column("fees", sa.Numeric(), nullable=False),
        sa.Column("funding", sa.Numeric(), nullable=False),
        sa.Column("net_pnl", sa.Numeric(), nullable=False),
        sa.Column("net_return_pct", sa.Numeric(), nullable=True),
        sa.Column("exit_reason", sa.String(length=64), nullable=False),
        sa.Column("liquidated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint(
            "(entry_price > '-Infinity'::numeric AND entry_price < 'Infinity'::numeric) AND (exit_price > '-Infinity'::numeric AND exit_price < 'Infinity'::numeric) AND (quantity > '-Infinity'::numeric AND quantity < 'Infinity'::numeric) AND (gross_pnl > '-Infinity'::numeric AND gross_pnl < 'Infinity'::numeric) AND (fees > '-Infinity'::numeric AND fees < 'Infinity'::numeric) AND (funding > '-Infinity'::numeric AND funding < 'Infinity'::numeric) AND (net_pnl > '-Infinity'::numeric AND net_pnl < 'Infinity'::numeric) AND (net_return_pct > '-Infinity'::numeric AND net_return_pct < 'Infinity'::numeric)",
            name=op.f("ck_backtest_trades_numeric_finite"),
        ),
        sa.CheckConstraint(
            "entry_price > 0 AND exit_price > 0 AND quantity > 0 AND fees >= 0",
            name=op.f("ck_backtest_trades_trade_amounts"),
        ),
        sa.CheckConstraint("exit_time >= entry_time", name=op.f("ck_backtest_trades_trade_times")),
        sa.CheckConstraint(
            "net_pnl = gross_pnl - fees + funding", name=op.f("ck_backtest_trades_net_pnl")
        ),
        sa.CheckConstraint("trade_number > 0", name=op.f("ck_backtest_trades_trade_number")),
        sa.ForeignKeyConstraint(
            ["run_id"], ["backtest_runs.id"], name=op.f("fk_backtest_trades_run_id_backtest_runs")
        ),
        sa.PrimaryKeyConstraint("run_id", "trade_number", name=op.f("pk_backtest_trades")),
    )


def downgrade() -> None:
    op.drop_table("backtest_trades")
    op.drop_index("ix_sync_jobs_market_dataset_started", table_name="sync_jobs")
    op.drop_table("sync_jobs")
    op.drop_table("funding_rates")
    op.drop_table("data_coverage")
    op.drop_table("candles")
    op.drop_index("ix_backtest_runs_market_created", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_strategy_created", table_name="backtest_runs")
    op.drop_table("backtest_runs")
    op.drop_table("markets")
