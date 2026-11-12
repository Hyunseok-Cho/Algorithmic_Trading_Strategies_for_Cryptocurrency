"""TP barriers, ambiguous candles, gaps and RSI signal preservation for v3."""

from dataclasses import replace
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tests.fixtures.scenarios import HOUR, START, ScheduledStrategy, bars, request
from tests.test_rsi_strategy import context
from trading_lab.backtesting.engine import run_engine
from trading_lab.backtesting.portfolio import Portfolio
from trading_lab.backtesting.risk import protective_target_exit
from trading_lab.config import BACKEND_DIR
from trading_lab.domain.enums import DirectionMode, SignalAction
from trading_lab.interfaces.cli import load_request
from trading_lab.strategies.registry import create_strategy


def v3_request(count=4, **changes):
    values = dict(strategy_id="rsi", strategy_version="v3", stop_loss_pct="10",
                  take_profit_pct="20", market_type="perpetual", symbol="BTC/USDT:USDT",
                  direction_mode="long_short", funding_mode="assume_zero", leverage="1")
    values.update(changes)
    return request(count, **values)


@pytest.mark.parametrize("changes", [
    {"stop_loss_pct": None}, {"take_profit_pct": None},
    {"take_profit_pct": "0"}, {"take_profit_pct": "100"},
    {"take_profit_pct": "NaN"}, {"stop_loss_pct": "0"},
])
def test_v3_requires_valid_tp_and_sl(changes):
    with pytest.raises(ValidationError):
        v3_request(**changes)


def test_v3_rejects_wrong_request_even_when_injected_directly():
    with pytest.raises(ValueError, match="rsi/v3"):
        run_engine(request(), bars([100] * 4), create_strategy("rsi", {}, version="v3"))


@pytest.mark.parametrize("mode", list(DirectionMode))
def test_v3_preserves_v1_rsi_signals(mode):
    first = create_strategy("rsi", {"period": 2})
    third = create_strategy("rsi", {"period": 2}, version="v3")
    prices = [100, 99, 98, 101, 104, 90]
    for end in range(1, len(prices) + 1):
        ctx = context(prices[:end], mode=mode)
        assert third.on_bar(ctx) == first.on_bar(ctx)


@pytest.mark.parametrize("side,low,high,target", [
    ("long", 99, 125, 120), ("short", 75, 101, 80),
])
def test_intrabar_tp_and_opening_only_has_no_lookahead(side, low, high, target):
    portfolio = Portfolio(v3_request())
    portfolio.open(side, Decimal(100), START)
    candle = replace(bars([100])[0], low=Decimal(low), high=Decimal(high))
    assert protective_target_exit(portfolio, candle, opening_only=True) is None
    assert protective_target_exit(portfolio, candle) == (Decimal(target), "take_profit", False)


@pytest.mark.parametrize("side,opening", [("long", 125), ("short", 75)])
def test_tp_gap_is_known_before_later_adverse_extremes(side, opening):
    portfolio = Portfolio(v3_request())
    portfolio.open(side, Decimal(100), START)
    candle = replace(bars([opening])[0], low=Decimal(50), high=Decimal(150))
    assert protective_target_exit(portfolio, candle) == (Decimal(opening), "take_profit", False)
    assert protective_target_exit(portfolio, candle, opening_only=True) == (
        Decimal(opening), "take_profit", False,
    )


@pytest.mark.parametrize("side,expected", [("long", 90), ("short", 110)])
def test_sl_wins_when_both_sides_touched_from_neutral_open(side, expected):
    portfolio = Portfolio(v3_request(leverage="5"))
    portfolio.open(side, Decimal(100), START)
    candle = replace(bars([100])[0], low=Decimal(70), high=Decimal(130))
    assert protective_target_exit(portfolio, candle) == (Decimal(expected), "stop_loss", False)


@pytest.mark.parametrize("side,opening", [("long", 70), ("short", 130)])
def test_liquidation_gap_is_not_rescued_by_later_tp(side, opening):
    portfolio = Portfolio(v3_request(leverage="5"))
    portfolio.open(side, Decimal(100), START)
    candle = replace(bars([opening])[0], low=Decimal(50), high=Decimal(150))
    assert protective_target_exit(portfolio, candle) == (Decimal(opening), "liquidation", True)


def test_tp_execution_pays_costs_and_keeps_next_open_entry_rule():
    candles = list(bars([100] * 4))
    candles[2] = replace(candles[2], high=Decimal(130))
    req = v3_request(fee_rate_open="0.001", fee_rate_close="0.001", slippage_bps="10")
    account, _, assumptions, _ = run_engine(
        req, candles, ScheduledStrategy({0: SignalAction.TARGET_LONG})
    )
    trade, = account.trades
    assert trade.entry_time == START + HOUR and trade.entry_price == Decimal("100.1")
    expected = Decimal("100.1") * Decimal("1.2") * Decimal("0.999")
    assert abs(trade.exit_price - expected) < Decimal("1e-40")
    assert trade.exit_reason == "take_profit" and not trade.liquidated
    assert trade.exit_time == START + 3 * HOUR
    assert trade.fees > 0 and trade.net_pnl < trade.gross_pnl
    assert any("intrabar adverse exits win" in item for item in assumptions)


def test_opening_tp_precedes_queued_reversal():
    candles = bars([100, 100, 125, 125])
    strategy = ScheduledStrategy({0: SignalAction.TARGET_LONG, 1: SignalAction.TARGET_SHORT})
    account, _, _, _ = run_engine(v3_request(), candles, strategy)
    first, second = account.trades
    assert first.exit_reason == "take_profit" and first.exit_price == 125
    assert first.exit_time == second.entry_time == START + 2 * HOUR
    assert second.position_side == "short"


def test_rsi_reversal_stays_active_without_tp_touch():
    strategy = ScheduledStrategy({0: SignalAction.TARGET_LONG, 1: SignalAction.TARGET_SHORT})
    account, _, _, _ = run_engine(v3_request(), bars([100] * 4), strategy)
    assert [trade.exit_reason for trade in account.trades] == ["reversal", "end_of_test"]


def test_reentry_remains_enabled_after_tp():
    candles = list(bars([100] * 5))
    candles[2] = replace(candles[2], high=Decimal(125))
    strategy = ScheduledStrategy({0: SignalAction.TARGET_LONG, 2: SignalAction.TARGET_LONG})
    account, _, _, _ = run_engine(v3_request(5), candles, strategy)
    first, second = account.trades
    assert first.exit_reason == "take_profit"
    assert second.entry_time == START + 3 * HOUR


@pytest.mark.parametrize("mode", ["long_only", "short_only", "long_short"])
def test_v3_configs_change_only_version_and_tp(mode):
    parent = f"future/{mode}/BTC_USDT_USDT/1h/1x"
    old = load_request(BACKEND_DIR / f"config/rsi/v2/{parent}/rsi_v2_btc_perpetual_1h_1x_{mode}_sl10.yaml")
    new = load_request(BACKEND_DIR / f"config/rsi/v3/{parent}/rsi_v3_btc_perpetual_1h_1x_{mode}_sl10_tp20.yaml")
    assert new.strategy_version == "v3" and new.stop_loss_pct == 10 and new.take_profit_pct == 20
    ignored = {"strategy_version", "take_profit_pct"}
    assert new.model_dump(exclude=ignored) == old.model_dump(exclude=ignored)
    create_strategy("rsi", new.strategy_parameters, version="v3").validate_request(new)
