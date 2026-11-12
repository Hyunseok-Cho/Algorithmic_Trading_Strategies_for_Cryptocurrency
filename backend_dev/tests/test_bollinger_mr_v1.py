"""Regression coverage for band crossings and the moving exit target."""

from decimal import Decimal

import pytest
from backend_dev.indicators.bollinger import Bands, bollinger_bands
from backend_dev.run_backtest import DEV_DIR, main
from backend_dev.strategies.bollinger_mr.v1 import UserStrategy
from backend_dev.tests.test_macd_dev import HOUR, START, candles, context, request
from trading_lab.backtesting.engine import run_engine
from trading_lab.domain.enums import DirectionMode
from trading_lab.interfaces.cli import load_request


def test_population_standard_deviation():
    assert bollinger_bands((Decimal(90), Decimal(110)), Decimal(2)) == Bands(
        Decimal(100), Decimal(80), Decimal(120)
    )


@pytest.mark.parametrize(
    "side,sign,mode",
    [
        ("long", 1, DirectionMode.LONG_ONLY),
        ("short", -1, DirectionMode.SHORT_ONLY),
    ],
)
@pytest.mark.parametrize("exit_middle,exit_bar", [("dynamic", 7), ("fixed", 8)])
def test_middle_exit_executes_on_next_open(side, sign, mode, exit_middle, exit_bar):
    strategy = UserStrategy(period=4, deviations="1", exit_middle=exit_middle)
    prices = [100 + sign * delta for delta in (0, 0, -1, 0, -20, -15, -6, -5, -4)]
    req = request(future=side == "short").model_copy(
        update={"strategy_id": "bollinger_mr", "direction_mode": mode}
    )
    account, _, _, _ = run_engine(req, candles(prices), strategy)
    (trade,) = account.trades
    assert trade.position_side == side
    assert trade.entry_time == START + 5 * HOUR
    assert trade.exit_time == START + exit_bar * HOUR
    assert trade.exit_reason == "signal"
    assert strategy.signal_bands[trade.entry_time].middle == 100 - sign * Decimal("5.25")
    observed_middle = Decimal("10.25") if exit_middle == "dynamic" else Decimal("11.5")
    assert strategy.signal_bands[trade.exit_time].middle == 100 - sign * observed_middle
    assert trade.entry_price == prices[5]
    assert float(trade.exit_price) == pytest.approx(prices[exit_bar])


def test_requires_fresh_cross_and_respects_direction():
    strategy = UserStrategy(period=4, deviations="1")
    assert strategy.on_bar(context([100, 100, 100, 100])) is None
    assert strategy.on_bar(context([100, 100, 100, 100, 100])) is None
    assert strategy.on_bar(context([100, 100, 100, 80, 78])) is None
    assert strategy.on_bar(
        context([100, 100, 99, 100, 80], mode=DirectionMode.SHORT_ONLY)
    ) is None


def test_batch_matrix_and_config_validation():
    paths = sorted((DEV_DIR / "config/bollinger_mr/v1").glob("*.yaml"))
    assert len(paths) == 16
    matrix = set()
    for path in paths:
        req = load_request(path)
        assert main(["--config", str(path), "--check"]) == 0
        matrix.add((req.market_type.value, req.direction_mode.value, req.leverage))
    assert matrix == {("spot", "long_only", 1)} | {
        ("perpetual", direction, leverage)
        for direction in ("long_only", "short_only", "long_short")
        for leverage in range(1, 6)
    }
