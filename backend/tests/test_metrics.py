from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.fixtures.scenarios import HOUR, START, NoTrades, ScheduledStrategy, bars, request
from trading_lab.application.dto import EquityPoint
from trading_lab.backtesting.engine import run_engine
from trading_lab.backtesting.metrics import calculate_metrics


def test_initial_equity_is_included_in_drawdown_and_winning_profit_factor_is_na():
    req = request(fee_rate_open="0.001", fee_rate_close="0.001")
    candles = bars([100, 100, 90, 120])
    account, curve, _, _ = run_engine(req, candles, ScheduledStrategy())
    summary, _ = calculate_metrics(req, account, curve, candles)
    assert summary["max_drawdown"] > 100
    assert summary["max_drawdown_pct"] > 10
    assert summary["profit_factor"] is None
    assert summary["winning_trades"] == 1
    assert summary["average_trades_per_calendar_day"] == 1


def test_sharpe_sortino_use_utc_daily_returns_and_365_day_annualization():
    req = request(72)
    values = [Decimal("1000"), Decimal("1100"), Decimal("990"), Decimal("1089")]
    curve = tuple(
        EquityPoint(
            time=START + index * 24 * HOUR,
            equity=value,
            cash=value,
            margin=Decimal(0),
            unrealized_pnl=Decimal(0),
        )
        for index, value in enumerate(values)
    )
    trade = SimpleNamespace(
        net_pnl=Decimal("89"),
        position_side="long",
        net_return_pct=Decimal("8.9"),
        duration_seconds=86400,
        exit_time=req.end_time,
    )
    portfolio = SimpleNamespace(
        trades=[trade],
        total_gross=Decimal("89"),
        total_fees=Decimal(0),
        total_funding=Decimal(0),
        total_price_pnl=Decimal("89"),
        total_adjustment=Decimal(0),
        order_count=2,
        position=None,
    )
    summary, daily = calculate_metrics(req, portfolio, curve, bars([100] * 72))
    assert [row["return_pct"] for row in daily] == [Decimal("10"), Decimal("-10"), Decimal("10")]
    assert summary["sharpe"] == pytest.approx(5.5151307026)
    assert summary["sortino"] == pytest.approx(11.0302614052)
    assert summary["max_drawdown_pct"] == 10
    assert summary["calendar_days"] == 3
    assert daily[-1]["completed_trades"] == 1


def test_total_loss_and_zero_equity_do_not_produce_infinite_json_values():
    from trading_lab.domain.enums import SignalAction

    req = request(
        market_type="perpetual",
        symbol="BTC/USDT:USDT",
        leverage="10",
        funding_mode="assume_zero",
        liquidation_fee_rate="0",
    )
    candles = bars([100, 100, 1, 1])
    account, curve, _, _ = run_engine(req, candles, ScheduledStrategy({0: SignalAction.OPEN_LONG}))
    summary, daily = calculate_metrics(req, account, curve, candles)
    assert summary["total_return_pct"] == -100
    assert summary["max_drawdown_pct"] == 100
    assert summary["profit_factor"] == 0
    assert summary["average_profit"] is None
    assert summary["sharpe"] is None


def test_no_trade_multi_day_risk_is_explicitly_undefined():
    req, candles = request(72), bars([100] * 72)
    portfolio, curve, _, _ = run_engine(req, candles, NoTrades())
    summary, _ = calculate_metrics(req, portfolio, curve, candles)
    assert summary["sharpe"] is None
    assert summary["sortino"] is None
    assert summary["expectancy"] is None
