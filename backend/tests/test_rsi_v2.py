"""Protective SL barriers, gap sequencing, unchanged RSI signals and v2 settings."""

from dataclasses import replace
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tests.fixtures.scenarios import HOUR, START, ScheduledStrategy, bars, request
from tests.test_rsi_strategy import context
from trading_lab.backtesting.engine import run_engine
from trading_lab.backtesting.portfolio import Portfolio
from trading_lab.backtesting.risk import protective_stop_exit, risk_exit
from trading_lab.config import BACKEND_DIR
from trading_lab.domain.enums import DirectionMode, SignalAction
from trading_lab.interfaces.cli import load_request
from trading_lab.strategies.registry import create_strategy


def v2_request(count=4, **changes):
    values = dict(strategy_id="rsi", strategy_version="v2", stop_loss_pct="2",
                  market_type="perpetual", symbol="BTC/USDT:USDT",
                  direction_mode="long_short", funding_mode="assume_zero", leverage="5")
    values.update(changes)
    return request(count, **values)


@pytest.mark.parametrize("changes", [
    {"stop_loss_pct": None}, {"stop_loss_pct": "0"},
    {"stop_loss_pct": "NaN"}, {"take_profit_pct": "4"},
])
def test_v2_requires_sl_and_forbids_tp(changes):
    with pytest.raises(ValidationError):
        v2_request(**changes)


def test_v2_cannot_be_injected_into_v1_run():
    strategy = create_strategy("rsi", {}, version="v2")
    with pytest.raises(ValueError, match="rsi/v2"):
        run_engine(request(), bars([100] * 4), strategy)


@pytest.mark.parametrize("mode", list(DirectionMode))
def test_v2_reuses_v1_rsi_signals(mode):
    v1 = create_strategy("rsi", {"period": 2})
    v2 = create_strategy("rsi", {"period": 2}, version="v2")
    prices = [100, 99, 98, 101, 104, 90]
    for end in range(1, len(prices) + 1):
        ctx = context(prices[:end], mode=mode)
        assert v2.on_bar(ctx) == v1.on_bar(ctx)
    assert v2.parameters == v1.parameters


@pytest.mark.parametrize("side,low,high,expected", [
    ("long", "70", "101", "98"), ("short", "99", "130", "102"),
])
def test_sl_is_first_continuous_adverse_barrier_and_legacy_is_unchanged(side, low, high, expected):
    portfolio = Portfolio(v2_request())
    portfolio.open(side, Decimal(100), START)
    candle = replace(bars([100])[0], low=Decimal(low), high=Decimal(high))
    assert risk_exit(portfolio, candle)[1] == "liquidation"  # Original policy retained.
    assert protective_stop_exit(portfolio, candle) == (Decimal(expected), "stop_loss", False)


@pytest.mark.parametrize("side,opening,reason", [
    ("long", 95, "stop_loss"), ("short", 105, "stop_loss"),
    ("long", 70, "liquidation"), ("short", 130, "liquidation"),
])
def test_opening_gaps_fill_at_open_and_cannot_skip_liquidation(side, opening, reason):
    portfolio = Portfolio(v2_request())
    portfolio.open(side, Decimal(100), START)
    candle = bars([opening])[0]
    assert protective_stop_exit(portfolio, candle, opening_only=True) == (
        Decimal(opening), reason, reason == "liquidation",
    )


@pytest.mark.parametrize("side,low,high", [("long", 70, 101), ("short", 99, 140)])
def test_liquidation_wins_when_stop_is_beyond_liquidation(side, low, high):
    portfolio = Portfolio(v2_request(stop_loss_pct="30"))
    portfolio.open(side, Decimal(100), START)
    candle = replace(bars([100])[0], low=Decimal(low), high=Decimal(high))
    assert protective_stop_exit(portfolio, candle)[1] == "liquidation"


def test_stop_fill_pays_fees_and_slippage():
    candles = list(bars([100] * 4))
    candles[2] = replace(candles[2], low=Decimal(95))
    req = v2_request(fee_rate_open="0.001", fee_rate_close="0.001", slippage_bps="10")
    strategy = ScheduledStrategy({0: SignalAction.OPEN_LONG})
    account, _, assumptions, _ = run_engine(req, candles, strategy)
    trade, = account.trades
    assert trade.entry_price == Decimal("100.1")
    expected_exit = Decimal("100.1") * Decimal("0.98") * Decimal("0.999")
    assert abs(trade.exit_price - expected_exit) < Decimal("1e-40")
    assert trade.exit_reason == "stop_loss" and not trade.liquidated
    assert trade.fees > 0 and trade.net_pnl < trade.gross_pnl
    assert trade.exit_time == START + 3 * HOUR
    assert any("nearest adverse" in item for item in assumptions)
    assert not any(item.startswith("OHLC risk priority:") for item in assumptions)


def test_gap_stop_precedes_queued_rsi_reversal():
    req = v2_request()
    candles = bars([100, 100, 95, 95])
    strategy = ScheduledStrategy({0: SignalAction.TARGET_LONG, 1: SignalAction.TARGET_SHORT})
    account, _, _, _ = run_engine(req, candles, strategy)
    first, second = account.trades
    assert first.exit_reason == "stop_loss"
    assert first.exit_price == 95
    assert first.exit_time == second.entry_time == START + 2 * HOUR
    assert second.position_side == "short"


def test_v2_allows_same_direction_reentry_after_stop():
    candles = list(bars([100] * 5))
    candles[2] = replace(candles[2], low=Decimal(95))
    strategy = ScheduledStrategy({0: SignalAction.TARGET_LONG, 2: SignalAction.TARGET_LONG})
    account, _, _, _ = run_engine(v2_request(5), candles, strategy)
    first, second = account.trades
    assert first.exit_reason == "stop_loss"
    assert second.position_side == "long" and second.entry_time == START + 3 * HOUR


@pytest.mark.parametrize("mode", ["long_only", "short_only", "long_short"])
def test_v2_example_configs(mode):
    req = load_request(
        BACKEND_DIR / f"config/rsi/v2/future/{mode}/BTC_USDT_USDT/1h/1x/"
        f"rsi_v2_btc_perpetual_1h_1x_{mode}_sl2.yaml"
    )
    assert req.strategy_version == "v2" and req.direction_mode.value == mode
    assert req.leverage == 1 and req.stop_loss_pct == 2 and req.take_profit_pct is None
    create_strategy("rsi", req.strategy_parameters, version="v2").validate_request(req)
