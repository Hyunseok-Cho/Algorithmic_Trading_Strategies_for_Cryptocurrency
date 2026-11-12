"""Development tests use synthetic bars and the shared engine; no DB/network."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from backend_dev.indicators.ema import EMA
from backend_dev.indicators.macd import MACD, MACDValue
from backend_dev.run_backtest import DEV_DIR, main
from backend_dev.strategies.macd.v1 import UserStrategy
from trading_lab.application.dto import BacktestRequest
from trading_lab.backtesting.engine import run_engine
from trading_lab.domain.enums import DirectionMode, SignalAction
from trading_lab.domain.models import Candle
from trading_lab.strategies.base import History, StrategyContext

START = datetime(2024, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


def candles(prices):
    return tuple(
        Candle(
            START + i * HOUR,
            Decimal(str(p)),
            Decimal(str(p)) + 1,
            Decimal(str(p)) - Decimal("0.5"),
            Decimal(str(p)),
            Decimal(1),
        )
        for i, p in enumerate(prices)
    )


def context(prices, *, mode=DirectionMode.LONG_SHORT, trading=True):
    data = candles(prices)
    return StrategyContext(
        data[-1].open_time + HOUR,
        History(data, len(data)),
        Decimal(1000),
        Decimal(1000),
        None,
        trading,
        mode,
    )


def request(*, future=False):
    return BacktestRequest(
        strategy_id="macd",
        strategy_version="v1",
        symbol="BTC/USDT:USDT" if future else "BTC/USDT",
        market_type="perpetual" if future else "spot",
        timeframe="1h",
        direction_mode="long_short" if future else "long_only",
        leverage="2" if future else "1",
        start_time=START + 4 * HOUR,
        end_time=START + 9 * HOUR,
        initial_capital="1000",
        fee_rate_open="0",
        fee_rate_close="0",
        slippage_bps="0",
        warmup_bars=4,
        funding_mode="assume_zero" if future else "strict",
    )


def test_ema_seed_smoothing_and_signed_inputs():
    ema = EMA(3)
    assert [ema.update(Decimal(i)) for i in [1, 2, 3, 4]] == [None, None, Decimal(2), Decimal(3)]
    signed = EMA(3)
    assert [signed.update(Decimal(i)) for i in [-3, -2, -1, 0]] == [
        None,
        None,
        Decimal(-2),
        Decimal(-1),
    ]
    single = EMA(1)
    assert [single.update(Decimal(i)) for i in [0, -1, 3]] == list(map(Decimal, [0, -1, 3]))


@pytest.mark.parametrize(
    "params",
    [
        {"fast": True},
        {"slow": 0},
        {"signal": 10001},
        {"signal": "9"},
        {"fast": 26, "slow": 26},
        {"fast": 30, "slow": 26},
    ],
)
def test_invalid_periods(params):
    with pytest.raises(ValueError):
        MACD(**params)


@pytest.mark.parametrize("value", [Decimal(0), Decimal(-1), Decimal("NaN"), 100.0, None])
def test_bad_close_does_not_mutate_state(value):
    indicator = MACD()
    with pytest.raises(ValueError):
        indicator.update(value)
    assert indicator._fast.samples == indicator._slow.samples == 0


def test_macd_hand_calculated_seed_and_next_values():
    indicator = MACD(2, 3, 2)
    values = [indicator.update(Decimal(i)) for i in [1, 2, 3, 4, 3]]
    assert values[:3] == [None] * 3
    assert values[3] == MACDValue(Decimal("0.5"), Decimal("0.5"), Decimal(0))
    assert abs(values[4].macd - Decimal(1) / 6) < Decimal("1e-25")
    assert abs(values[4].signal - Decimal(5) / 18) < Decimal("1e-25")
    assert abs(values[4].histogram + Decimal(1) / 9) < Decimal("1e-25")


def test_default_first_full_value_needs_34_closes_and_is_causal():
    first, second = MACD(), MACD()
    a = [first.update(Decimal(p)) for p in [100] * 34 + [999]]
    b = [second.update(Decimal(p)) for p in [100] * 34 + [1]]
    assert a[:33] == [None] * 33
    assert a[33] == MACDValue(Decimal(0), Decimal(0), Decimal(0))
    assert a[:34] == b[:34]


@pytest.mark.parametrize(
    "mode,buy,sell",
    [
        (DirectionMode.LONG_ONLY, SignalAction.TARGET_LONG, SignalAction.CLOSE),
        (DirectionMode.SHORT_ONLY, SignalAction.CLOSE, SignalAction.TARGET_SHORT),
        (DirectionMode.LONG_SHORT, SignalAction.TARGET_LONG, SignalAction.TARGET_SHORT),
    ],
)
def test_crossings_equality_direction_and_repeated_callback(mode, buy, sell):
    strategy = UserStrategy(2, 3, 2)
    values = iter([MACDValue(Decimal(h), Decimal(0), Decimal(h)) for h in [-1, 0, 1, 0, -1]])
    strategy._macd = SimpleNamespace(update=lambda close: next(values))
    prices = [100] * 5
    results = []
    for end in range(1, 6):
        ctx = context(prices[:end], mode=mode)
        result = strategy.on_bar(ctx)
        results.append(result.action if result else None)
        assert strategy.on_bar(ctx) is None  # No repeated signal for an already processed bar.
    assert results == [None, None, buy, None, sell]


def test_warmup_updates_previous_histogram_without_orders():
    strategy = UserStrategy(2, 3, 2)
    assert strategy.on_bar(context([100] * 4, trading=False)) is None
    assert strategy.on_bar(context([100] * 4 + [110])).action is SignalAction.TARGET_LONG
    with pytest.raises(ValueError, match="earlier history"):
        strategy.on_bar(context([100]))


@pytest.mark.parametrize("future", [False, True])
def test_shared_engine_next_open_exit_or_reverse(future):
    data = candles([100, 100, 100, 100, 110, 110, 90, 90, 90])
    account, _, _, _ = run_engine(request(future=future), data, UserStrategy(2, 3, 2))
    first = account.trades[0]
    assert first.entry_time == START + 5 * HOUR and first.entry_price == 110
    assert first.exit_time == START + 7 * HOUR
    assert abs(first.exit_price - Decimal(90)) < Decimal("1e-40")
    if future:
        assert first.exit_reason == "reversal"
        assert account.trades[1].position_side == "short"
        assert account.trades[1].entry_time == first.exit_time
    else:
        assert len(account.trades) == 1 and first.exit_reason == "signal"


def test_v1_rejects_tp_sl_and_insufficient_warmup():
    strategy = UserStrategy(2, 3, 2)
    with pytest.raises(ValueError, match="TP/SL"):
        strategy.validate_request(request().model_copy(update={"stop_loss_pct": Decimal(2)}))
    with pytest.raises(ValueError, match="warmup_bars"):
        strategy.validate_request(request().model_copy(update={"warmup_bars": 0}))


def test_five_yaml_configs_validate_without_database(monkeypatch):
    import backend_dev.run_backtest as runner

    monkeypatch.setattr(runner, "Settings", lambda: pytest.fail("Must not access DB"))
    paths = list((DEV_DIR / "config/macd/v1").rglob("*.yaml"))
    assert len(paths) == 5
    for path in paths:
        assert main(["--config", str(path), "--check"]) == 0
