"""Regression coverage for the combined strategy's protective re-entry lock."""

from dataclasses import replace
from decimal import Decimal

import pytest
from trading_lab.domain.enums import SignalAction
from trading_lab.interfaces.cli import load_request

from backend_dev.backtesting.engine import run_engine
from backend_dev.indicators.macd import MACDValue
from backend_dev.run_backtest import DEV_DIR
from backend_dev.strategies.rsi_macd.v4 import UserStrategy as V4
from backend_dev.tests.test_combined_risk import req, strategy
from backend_dev.tests.test_macd_dev import HOUR, START, candles, context


@pytest.mark.parametrize(
    "side,reason,inside,boundary,direction,action",
    [
        ("long", "stop_loss", 37, 38, 1, SignalAction.TARGET_LONG),
        ("short", "take_profit", 71, 70, -1, SignalAction.TARGET_SHORT),
    ],
)
def test_only_protected_side_waits_for_rsi_reset(
    side, reason, inside, boundary, direction, action
):
    instance = V4()
    bullish = MACDValue(Decimal(1), Decimal(0), Decimal(1))
    bearish = MACDValue(Decimal(-1), Decimal(0), Decimal(-1))
    same_macd, opposite_macd = (bullish, bearish) if direction == 1 else (bearish, bullish)
    ctx = context([100])
    instance.on_risk_exit(side, reason)
    assert instance._decide(Decimal(inside), same_macd, ctx) is None
    assert instance._decide(Decimal(boundary), same_macd, ctx) is None
    assert instance._decide(Decimal(inside), same_macd, ctx).action is action
    instance.on_risk_exit(side, reason)
    opposite_rsi = Decimal(71 if direction == 1 else 37)
    assert instance._decide(opposite_rsi, opposite_macd, ctx) is not None


@pytest.mark.parametrize(
    "tp,field,value,reason",
    [(None, "low", "100", "stop_loss"), (Decimal(10), "high", "125", "take_profit")],
)
def test_engine_notifies_before_close_signal(tp, field, value, reason):
    request = req("v4", future=True).model_copy(update={"take_profit_pct": tp})
    data = list(candles([100, 100, 100, 100, 110, 110, 110, 90, 90]))
    data[5] = replace(data[5], **{field: Decimal(value)})
    account, _, _, _ = run_engine(request, data, strategy(V4))
    assert [trade.exit_reason for trade in account.trades] == [reason, "end_of_test"]
    assert account.trades[1].entry_time == START + 7 * HOUR
    assert account.trades[1].position_side == "short"


def test_matrix_and_future_only_validation():
    root = DEV_DIR / "config/rsi_macd/v4"
    actual = set()
    for path in root.rglob("*.yaml"):
        request = load_request(path)
        V4().validate_request(request)
        assert request.leverage == 1
        actual.add((request.direction_mode.value, request.stop_loss_pct, request.take_profit_pct))
    assert actual == {
        (mode, sl, tp)
        for mode in ("long_only", "short_only", "long_short")
        for sl in (2, 4)
        for tp in (None, sl * 2)
    }
    with pytest.raises(ValueError, match="perpetual 1h"):
        V4().validate_request(req("v4"))
