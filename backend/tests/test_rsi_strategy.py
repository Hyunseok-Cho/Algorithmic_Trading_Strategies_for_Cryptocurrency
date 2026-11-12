"""Numerical RSI checks and user-band target behavior, independent of real markets."""

from decimal import Decimal

import pytest

from tests.fixtures.scenarios import HOUR, START, bars, request
from trading_lab.backtesting.engine import run_engine
from trading_lab.domain.enums import DirectionMode, SignalAction
from trading_lab.strategies.base import History, StrategyContext
from trading_lab.strategies.RSI_MACD.indicators import WilderRSI
from trading_lab.strategies.RSI_MACD.RSI.strategy import UserStrategy


def context(prices, *, mode=DirectionMode.LONG_ONLY, trading=True):
    candles = bars(prices)
    return StrategyContext(
        candles[-1].open_time + HOUR,
        History(candles, len(candles)),
        Decimal(1000),
        Decimal(1000),
        None,
        trading,
        mode,
    )


def test_wilder_seed_and_next_value_match_hand_calculated_reference():
    # Fourteen changes: gains sum to 3.34 and losses sum to 1.40.
    prices = [
        "44.34",
        "44.09",
        "44.15",
        "43.61",
        "44.33",
        "44.83",
        "45.10",
        "45.42",
        "45.84",
        "46.08",
        "45.89",
        "46.03",
        "45.61",
        "46.28",
        "46.28",
        "46.00",
    ]
    indicator = WilderRSI(14)
    values = [indicator.update(Decimal(value)) for value in prices]
    assert all(value is None for value in values[:14])
    assert abs(values[14] - Decimal("70.4641350210970464135021097")) < Decimal("1e-24")
    assert abs(values[15] - Decimal("66.2496185535551")) < Decimal("1e-12")


@pytest.mark.parametrize(
    ("prices", "expected"),
    [
        ([100, 101, 102], Decimal(100)),
        ([100, 99, 98], Decimal(0)),
        ([100, 100, 100], Decimal(50)),
        ([100, 101, 100], Decimal(50)),
    ],
)
def test_gain_loss_and_flat_edge_cases(prices, expected):
    indicator = WilderRSI(2)
    values = [indicator.update(Decimal(value)) for value in prices]
    assert values[-1] == expected


@pytest.mark.parametrize("invalid", [0, -1, float("nan"), Decimal("NaN"), Decimal(0)])
def test_invalid_close_is_rejected(invalid):
    with pytest.raises(ValueError):
        WilderRSI().update(invalid)


@pytest.mark.parametrize(
    ("mode", "low_action", "high_action"),
    [
        (DirectionMode.LONG_ONLY, SignalAction.TARGET_LONG, SignalAction.CLOSE),
        (DirectionMode.SHORT_ONLY, SignalAction.CLOSE, SignalAction.TARGET_SHORT),
        (DirectionMode.LONG_SHORT, SignalAction.TARGET_LONG, SignalAction.TARGET_SHORT),
    ],
)
def test_shared_rsi_uses_direction_policy_instead_of_market_specific_math(
    mode, low_action, high_action
):
    assert UserStrategy(period=2).on_bar(context([100, 99, 98], mode=mode)).action is low_action
    assert UserStrategy(period=2).on_bar(context([100, 101, 102], mode=mode)).action is high_action


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("37.9999"), SignalAction.TARGET_LONG),
        (Decimal("38"), None),
        (Decimal("50"), None),
        (Decimal("70"), None),
        (Decimal("70.0001"), SignalAction.TARGET_SHORT),
    ],
)
def test_strict_threshold_boundaries(value, expected):
    strategy = UserStrategy(period=2)
    ctx = context([100, 99, 98], mode=DirectionMode.LONG_SHORT)
    strategy.on_bar(ctx)
    strategy._rsi.value = value  # Isolate decision boundaries from numerical rounding.
    intent = strategy.on_bar(ctx)
    assert (intent.action if intent else None) is expected


def test_streaming_repeated_callback_does_not_count_a_bar_twice():
    strategy = UserStrategy(period=2)
    ctx = context([100, 99, 98])
    first = strategy.on_bar(ctx)
    changes = strategy._rsi.changes
    assert strategy.on_bar(ctx) == first
    assert strategy._rsi.changes == changes == 2
    assert strategy.on_bar(context([100, 99, 98], trading=False)) is None


def test_reusing_strategy_on_an_earlier_history_is_rejected():
    strategy = UserStrategy(period=2)
    strategy.on_bar(context([100, 99, 98]))
    with pytest.raises(ValueError, match="new strategy"):
        strategy.on_bar(context([100, 99]))


def test_indicator_is_prefix_causal():
    prefix = [Decimal(100 + index % 3) for index in range(20)]
    first, second = WilderRSI(14), WilderRSI(14)
    first_values = [first.update(value) for value in prefix + [Decimal("999")]]
    second_values = [second.update(value) for value in prefix + [Decimal("1")]]
    assert first_values[:-1] == second_values[:-1]


@pytest.mark.parametrize(
    "parameters",
    [
        {"period": 1},
        {"period": True},
        {"period": "14"},
        {"lower": "70", "upper": "38"},
        {"lower": "0"},
        {"upper": "100"},
        {"lower": "NaN"},
    ],
)
def test_bad_strategy_parameters_are_rejected(parameters):
    with pytest.raises(ValueError):
        UserStrategy(**parameters)


def test_unknown_strategy_parameter_is_rejected():
    with pytest.raises(TypeError):
        UserStrategy(typo=1)


def test_rsi_spot_buys_low_and_exits_high_at_next_open():
    candles = bars([100, 90, 80, 85, 100, 90])
    req = request(6, start_time=START + 2 * HOUR, warmup_bars=2)
    account, _, _, _ = run_engine(req, candles, UserStrategy(period=2))
    assert len(account.trades) == 1 and account.order_count == 2
    assert account.trades[0].entry_time == START + 3 * HOUR
    assert account.trades[0].entry_price == 85
    assert account.trades[0].exit_time == START + 5 * HOUR
    assert abs(account.trades[0].exit_price - Decimal(90)) < Decimal("1e-40")


def test_rsi_perpetual_reverses_long_to_short_at_same_next_open():
    candles = bars([100, 90, 80, 85, 100, 90])
    req = request(
        6,
        market_type="perpetual",
        symbol="BTC/USDT:USDT",
        direction_mode="long_short",
        funding_mode="assume_zero",
        start_time=START + 2 * HOUR,
        warmup_bars=2,
    )
    account, _, _, _ = run_engine(req, candles, UserStrategy(period=2))
    assert [trade.position_side for trade in account.trades] == ["long", "short"]
    assert account.trades[0].exit_reason == "reversal"
    assert account.trades[0].exit_time == account.trades[1].entry_time == START + 5 * HOUR
    assert account.order_count == 4


def test_rsi_requires_explicit_warmup_for_first_analysis_value():
    with pytest.raises(ValueError, match="warmup_bars >= 14"):
        run_engine(request(), bars([100] * 4), UserStrategy())
