from dataclasses import replace
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tests.fixtures.scenarios import HOUR, START, NoTrades, ScheduledStrategy, bars, request
from trading_lab.backtesting.engine import run_engine
from trading_lab.backtesting.metrics import calculate_metrics
from trading_lab.domain.enums import SignalAction
from trading_lab.domain.exceptions import DataCoverageError
from trading_lab.domain.models import FundingRate
from trading_lab.strategies.base import OrderIntent


def test_spot_next_open_and_prefix_history():
    strategy = ScheduledStrategy()
    candles = bars([100, 100, 110, 120])
    account, curve, _, _ = run_engine(request(), candles, strategy)
    trade = account.trades[0]
    assert trade.entry_time == START + HOUR
    assert trade.exit_time == START + 3 * HOUR
    assert trade.net_pnl == 200
    assert curve[-1].equity == 1200
    assert account.order_count == 2
    assert len(strategy.contexts[0].history) == 1
    assert strategy.contexts[0].history[:] == (candles[0],)
    with pytest.raises(IndexError):
        strategy.contexts[0].history[1]


def test_fees_slippage_and_conservation():
    req = request(fee_rate_open="0.001", fee_rate_close="0.002", slippage_bps="10")
    account, curve, _, _ = run_engine(req, bars([100, 100, 110, 120]), ScheduledStrategy())
    assert account.trades[0].entry_price == Decimal("100.100")
    assert account.trades[0].exit_price == Decimal("119.880")
    assert account.trades[0].fees > 0
    assert curve[-1].equity - req.initial_capital == account.total_gross - account.total_fees
    assert account.cash >= 0


@pytest.mark.parametrize(
    ("side", "prices", "expected"),
    [
        (SignalAction.OPEN_LONG, [100, 100, 110, 120], 400),
        (SignalAction.OPEN_SHORT, [100, 100, 90, 80], 400),
    ],
)
def test_linear_perpetual_long_short_and_leverage(side, prices, expected):
    req = request(
        market_type="perpetual",
        symbol="BTC/USDT:USDT",
        direction_mode="long_short",
        leverage="2",
        funding_mode="assume_zero",
    )
    account, curve, _, warnings = run_engine(
        req, bars(prices), ScheduledStrategy({0: side, 2: SignalAction.CLOSE})
    )
    assert account.trades[0].net_pnl == expected
    assert curve[-1].equity == 1000 + expected
    assert warnings


def test_partial_close_is_one_round_trip_and_three_orders():
    strategy = ScheduledStrategy(
        {
            0: SignalAction.OPEN_LONG,
            1: OrderIntent(SignalAction.CLOSE, Decimal("0.5")),
            2: SignalAction.CLOSE,
        }
    )
    account, curve, _, _ = run_engine(request(), bars([100, 100, 110, 120]), strategy)
    assert len(account.trades) == 1
    assert account.order_count == 3
    assert account.trades[0].exit_price == 115
    assert curve[-1].equity == 1150


def test_open_position_is_marked_without_counting_as_completed_trade():
    req = request(close_open_position_at_end=False)
    account, curve, _, _ = run_engine(
        req, bars([100, 100, 110, 125]), ScheduledStrategy({0: SignalAction.OPEN_LONG})
    )
    assert not account.trades
    assert curve[-1].equity == 1250
    assert curve[-1].unrealized_pnl == 250
    summary, _ = calculate_metrics(req, account, curve, bars([100, 100, 110, 125]))
    assert summary["open_positions"] == 1
    assert summary["completed_trades"] == 0


def test_funding_exact_boundary_and_strict_schedule():
    event = FundingRate(START + 2 * HOUR, Decimal("0.01"), "fixture", Decimal("100"))
    req = request(
        market_type="perpetual",
        symbol="BTC/USDT:USDT",
        expected_funding_times=[event.funding_time],
        funding_schedule_source="audited fixture",
    )
    account, curve, _, _ = run_engine(req, bars([100, 100, 100, 100]), ScheduledStrategy(), [event])
    assert account.total_funding == -10
    assert account.trades[0].net_pnl == -10
    assert curve[-1].equity == 990
    with pytest.raises(DataCoverageError):
        run_engine(req, bars([100] * 4), ScheduledStrategy(), [])
    with pytest.raises(DataCoverageError):
        run_engine(req, bars([100] * 4), ScheduledStrategy(), [replace(event, mark_price=None)])


def test_funding_at_entry_open_applies_only_to_carried_positions():
    event = FundingRate(START + HOUR, Decimal("0.01"), "fixture", Decimal("100"))
    req = request(
        market_type="perpetual",
        symbol="BTC/USDT:USDT",
        expected_funding_times=[event.funding_time],
        funding_schedule_source="audited fixture",
    )
    account, _, _, _ = run_engine(req, bars([100] * 4), ScheduledStrategy(), [event])
    assert account.total_funding == 0


def test_isolated_gap_liquidation_caps_loss_and_reports_adjustment():
    req = request(
        market_type="perpetual",
        symbol="BTC/USDT:USDT",
        leverage="10",
        funding_mode="assume_zero",
        liquidation_fee_rate="0",
    )
    account, curve, _, warnings = run_engine(req, bars([100, 100, 1, 1]), ScheduledStrategy())
    assert account.trades[0].liquidated
    assert account.trades[0].limited_loss_adjustment > 0
    assert curve[-1].equity == 0
    assert account.trades[0].net_pnl == -1000
    assert all(point.equity >= 0 and point.cash >= 0 for point in curve)
    assert any("loss cap" in value for value in warnings)


def test_stop_loss_wins_when_both_stop_and_target_are_touched():
    candles = list(bars([100, 100, 100, 100]))
    candles[1] = replace(candles[1], high=Decimal("120"), low=Decimal("80"))
    account, curve, _, _ = run_engine(
        request(stop_loss_pct="5", take_profit_pct="5"), candles, ScheduledStrategy()
    )
    assert account.trades[0].exit_reason == "stop_loss"
    assert curve[-1].equity == 950


def test_warmup_observations_do_not_place_orders():
    req = request(warmup_bars=2)
    strategy = ScheduledStrategy({0: SignalAction.OPEN_LONG, 2: SignalAction.OPEN_LONG})
    account, _, _, _ = run_engine(req, bars([100] * 6, start=START - 2 * HOUR), strategy)
    assert [context.trading_enabled for context in strategy.contexts[:3]] == [False, False, True]
    assert account.trades[0].entry_time == START + HOUR


def test_gap_and_wrong_direction_are_rejected():
    with pytest.raises(DataCoverageError):
        run_engine(request(), bars([100] * 3), NoTrades())
    with pytest.raises(ValueError, match="direction"):
        run_engine(request(), bars([100] * 4), ScheduledStrategy({0: SignalAction.OPEN_SHORT}))


@pytest.mark.parametrize(
    "changes",
    [
        {"initial_capital": "-1"},
        {"fee_rate_open": "NaN"},
        {"slippage_bps": "-1"},
        {"position_mode": "hedge"},
        {"leverage": "2"},
        {"direction_mode": "short_only"},
        {"start_time": START.replace(tzinfo=None)},
        {"warmup_bars": -1},
    ],
)
def test_invalid_requests_fail_before_engine(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_no_trades_and_no_losses_have_explicit_na_metrics():
    req, candles = request(), bars([100] * 4)
    portfolio, curve, _, _ = run_engine(req, candles, NoTrades())
    summary, daily = calculate_metrics(req, portfolio, curve, candles)
    assert summary["win_rate_pct"] is None
    assert summary["profit_factor"] is None
    assert summary["sharpe"] is None
    assert summary["max_drawdown"] == 0
    assert daily[0]["return_pct"] == 0


@pytest.mark.parametrize("perpetual", [False, True])
def test_multiple_partial_closes_reconcile_with_explicit_settlement_rounding(perpetual):
    from random import Random

    generator = Random(42)
    candles = bars([str(round(generator.uniform(80, 120), 8)) for _ in range(120)])
    actions = {}
    for index in range(0, 116, 5):
        actions[index] = SignalAction.OPEN_LONG
        actions[index + 2] = OrderIntent(SignalAction.CLOSE, Decimal("0.333333"))
        actions[index + 3] = SignalAction.CLOSE
    extra = (
        dict(
            market_type="perpetual",
            symbol="BTC/USDT:USDT",
            funding_mode="assume_zero",
            leverage="2",
        )
        if perpetual
        else {}
    )
    req = request(
        120,
        allocation_pct="37.3",
        fee_rate_open="0.00123",
        fee_rate_close="0.00234",
        slippage_bps="3.7",
        **extra,
    )
    account, curve, _, _ = run_engine(req, candles, ScheduledStrategy(actions))
    summary, _ = calculate_metrics(req, account, curve, candles)
    assert summary["completed_trades"] == 24
    assert abs(summary["settlement_rounding_residual"]) <= Decimal("1e-12") * account.order_count
    assert summary["net_pnl"] == (
        summary["realized_pnl"]
        + summary["unrealized_pnl"]
        + summary["settlement_rounding_residual"]
    )
