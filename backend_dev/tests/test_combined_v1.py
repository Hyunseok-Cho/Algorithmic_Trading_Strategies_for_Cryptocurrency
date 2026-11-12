"""MACD-state entry filter, shared RSI and independent opposite-RSI exits."""

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from backend_dev.indicators.macd import MACDValue
from backend_dev.run_backtest import DEV_DIR, main
from backend_dev.strategies.rsi_macd.v1 import UserStrategy
from backend_dev.tests.test_macd_dev import HOUR, START, candles, context, request
from trading_lab.backtesting.engine import run_engine
from trading_lab.domain.enums import DirectionMode, SignalAction
from trading_lab.interfaces.cli import load_request
from trading_lab.strategies.base import PositionView
from trading_lab.strategies.RSI_MACD.indicators import WilderRSI


@pytest.mark.parametrize(
    "rsi,line,signal,side,expected",
    [
        (37, -1, -2, None, SignalAction.TARGET_LONG),
        (71, -2, -1, None, SignalAction.TARGET_SHORT),
        (37, -2, -1, None, None),
        (71, -1, -2, None, None),
        (38, 1, 0, None, None),
        (70, -1, 0, None, None),
        (37, 0, 0, None, None),
        (71, 1, 0, "long", SignalAction.CLOSE),
        (71, -1, 0, "long", SignalAction.TARGET_SHORT),
        (71, 0, 0, "long", SignalAction.CLOSE),
        (50, -1, 0, "long", None),
        (37, 1, 0, "short", SignalAction.TARGET_LONG),
        (37, -1, 0, "short", SignalAction.CLOSE),
        (50, 1, 0, "short", None),
    ],
)
def test_entry_and_exit_rules(rsi, line, signal, side, expected):
    strategy = UserStrategy()
    ctx = context([100])
    if side:
        ctx = replace(ctx, position=PositionView(side, Decimal(1), Decimal(100)))
    value = MACDValue(Decimal(line), Decimal(signal), Decimal(line - signal))
    intent = strategy._decide(Decimal(rsi), value, ctx)
    assert (intent.action if intent else None) == expected


@pytest.mark.parametrize(
    "mode,rsi,hist",
    [
        (DirectionMode.LONG_ONLY, 71, -1),
        (DirectionMode.SHORT_ONLY, 37, 1),
    ],
)
def test_flat_entries_respect_allowed_direction(mode, rsi, hist):
    assert (
        UserStrategy()._decide(
            Decimal(rsi),
            MACDValue(Decimal(hist), Decimal(0), Decimal(hist)),
            context([100], mode=mode),
        )
        is None
    )


@pytest.mark.parametrize(
    "params",
    [
        {"rsi_period": True},
        {"lower": "NaN"},
        {"lower": "oops"},
        {"lower": "70", "upper": "38"},
        {"fast": 26, "slow": 12},
    ],
)
def test_invalid_parameters(params):
    with pytest.raises(ValueError):
        UserStrategy(**params)


def test_shared_rsi_and_warmup_then_no_duplicate_signal():
    strategy = UserStrategy()
    assert isinstance(strategy._rsi, WilderRSI)
    assert strategy.required_warmup_bars == 34
    strategy._rsi = SimpleNamespace(value=Decimal(37), update=lambda value: None)
    strategy._macd = SimpleNamespace(
        value=MACDValue(Decimal(-1), Decimal(-2), Decimal(1)), update=lambda value: None
    )
    assert strategy.on_bar(context([100], trading=False)) is None
    ctx = context([100, 100])
    assert strategy.on_bar(ctx).action is SignalAction.TARGET_LONG
    assert strategy.on_bar(ctx) is None
    with pytest.raises(ValueError, match="earlier history"):
        strategy.on_bar(context([100]))


@pytest.mark.parametrize("future", [False, True])
def test_shared_engine_next_open_and_filtered_reversal(future):
    strategy = UserStrategy(rsi_period=2, fast=2, slow=3, signal=2)

    class Feed:
        def __init__(self, values):
            self.values = iter(values)
            self.value = None

        def update(self, close):
            self.value = next(self.values)
            return self.value

    strategy._rsi = Feed(list(map(Decimal, [50, 50, 50, 50, 37, 50, 71, 50, 50])))
    strategy._macd = Feed(
        [MACDValue(Decimal(h), Decimal(0), Decimal(h)) for h in [-1, -1, 1, 1, 1, 1, -1, -1, -1]]
    )
    req = request(future=future).model_copy(update={"strategy_id": "rsi_macd"})
    account, _, _, _ = run_engine(
        req, candles([100, 100, 100, 100, 110, 110, 90, 90, 90]), strategy
    )
    first = account.trades[0]
    assert first.entry_time == START + 5 * HOUR
    assert first.exit_time == START + 7 * HOUR
    if future:
        assert first.exit_reason == "reversal" and account.trades[1].position_side == "short"
    else:
        assert len(account.trades) == 1 and first.exit_reason == "signal"


def test_request_validation_rejects_tp_sl_wrong_version_and_warmup():
    strategy = UserStrategy(rsi_period=2, fast=2, slow=3, signal=2)
    req = request().model_copy(update={"strategy_id": "rsi_macd"})
    strategy.validate_request(req)
    for update in (
        {"strategy_version": "v2"},
        {"stop_loss_pct": Decimal(2)},
        {"take_profit_pct": Decimal(4)},
        {"warmup_bars": 0},
    ):
        with pytest.raises(ValueError):
            strategy.validate_request(req.model_copy(update=update))


def test_five_configs_and_runner_check_without_database(monkeypatch):
    import backend_dev.run_backtest as runner

    monkeypatch.setattr(runner, "Settings", lambda: pytest.fail("Must not access DB"))
    paths = list((DEV_DIR / "config/rsi_macd/v1").rglob("*.yaml"))
    assert len(paths) == 5
    for path in paths:
        req = load_request(path)
        assert req.stop_loss_pct is None and req.take_profit_pct is None
        assert req.strategy_version == "v1"
        assert main(["--config", str(path), "--check"]) == 0
