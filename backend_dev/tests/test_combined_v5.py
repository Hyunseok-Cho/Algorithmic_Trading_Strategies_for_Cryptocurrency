"""Direction-specific V5 lock and sweep regression coverage."""

from dataclasses import replace
from decimal import Decimal

import pytest

from backend_dev.backtesting.engine import run_engine
from backend_dev.run_backtest import DEV_DIR
from backend_dev.run_v5_sweep import grid
from backend_dev.strategies.rsi_macd.v2 import UserStrategy as V2
from backend_dev.strategies.rsi_macd.v4 import UserStrategy as V4
from backend_dev.strategies.rsi_macd.v5 import LOCK_SIDES, UserStrategy as V5
from backend_dev.tests.test_combined_risk import req, strategy
from backend_dev.tests.test_macd_dev import candles
from trading_lab.interfaces.cli import load_request


@pytest.mark.parametrize("mode", LOCK_SIDES)
def test_protective_exit_locks_only_selected_directions(mode):
    for side in ("long", "short"):
        instance = V5(reentry_lock=mode)
        instance.on_risk_exit(side, "liquidation")
        assert not instance._locked_sides
        instance.on_risk_exit(side, "stop_loss")
        assert instance._locked_sides == ({side} if side in LOCK_SIDES[mode] else set())


@pytest.mark.parametrize("mode,reference", [("none", V2), ("both", V4)])
def test_grid_controls_match_existing_engines(mode, reference):
    data = list(candles([100, 100, 100, 100, 110, 110, 110, 90, 90]))
    data[5] = replace(data[5], low=Decimal(100))
    current, equity, _, _ = run_engine(
        req("v5", future=True), data, strategy(lambda **params: V5(reentry_lock=mode, **params))
    )
    baseline, baseline_equity, _, _ = run_engine(
        req(reference.strategy_version, future=True), data, strategy(reference)
    )
    assert current.trades == baseline.trades
    assert equity == baseline_equity


def test_sweep_includes_all_distinct_cases():
    cases = list(grid())
    assert len(cases) == len(set(cases)) == 1800
    assert (5, 10, 4, "short_only") in cases
    assert (1, 2, 20, "long_only") in cases


@pytest.mark.parametrize(
    "updates,reason,long_price,short_price",
    [
        ([(5, "high", "116"), (6, "high", "125"), (7, "low", "85")],
         "take_profit", "123.2", "86.4"),
        ([(5, "low", "106"), (6, "low", "104"), (7, "high", "92")],
         "stop_loss", "105.6", "91.8"),
    ],
)
def test_directional_protection_follows_held_position(updates, reason, long_price, short_price):
    data = list(candles([100, 100, 100, 100, 110, 110, 110, 90, 90]))
    for index, field, value in updates:
        data[index] = replace(data[index], **{field: Decimal(value)})
    config = DEV_DIR / "config/rsi_macd/v5/directional/btc_1h_long_short_2x.yaml"
    configured = load_request(config)
    request = req("v5", future=True).model_copy(
        update={"stop_loss_pct": None, "strategy_parameters": configured.strategy_parameters}
    )
    instance = strategy(lambda **params: V5(
        **params, reentry_lock="both",
        directional_protection=configured.strategy_parameters["directional_protection"],
    ))
    account, _, _, _ = run_engine(request, data, instance)
    assert [(trade.position_side, trade.exit_reason) for trade in account.trades] == [
        ("long", reason),
        ("short", reason),
    ]
    for trade, price in zip(account.trades, (long_price, short_price), strict=True):
        assert abs(trade.exit_price - Decimal(price)) < Decimal("1e-40")


def test_directional_configs_are_valid_and_exclude_common_risk():
    root = DEV_DIR / "config/rsi_macd/v5/directional"
    requests = [load_request(path) for path in root.glob("*.yaml")]
    assert sorted(request.leverage for request in requests) == list(range(1, 6))
    for request in requests:
        instance = V5(**request.strategy_parameters)
        instance.validate_request(request)
        assert instance.parameters["reentry_lock"] == "both"
        assert instance.directional_protection == {
            "long": {"stop_loss_pct": Decimal(4), "take_profit_pct": Decimal(12)},
            "short": {"stop_loss_pct": Decimal(2), "take_profit_pct": Decimal(4)},
        }
        with pytest.raises(ValueError, match="cannot be combined"):
            instance.validate_request(request.model_copy(update={"stop_loss_pct": Decimal(2)}))
