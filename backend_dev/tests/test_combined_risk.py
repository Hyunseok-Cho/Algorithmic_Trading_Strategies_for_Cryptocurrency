"""Combined protective versions preserve v1 signals and enforce risk settings."""

from dataclasses import replace
from decimal import Decimal

import pytest
from backend_dev.backtesting.engine import run_engine
from backend_dev.indicators.macd import MACDValue
from backend_dev.run_backtest import DEV_DIR, main
from backend_dev.strategies.rsi_macd.v1 import UserStrategy as V1
from backend_dev.strategies.rsi_macd.v2 import UserStrategy as V2
from backend_dev.strategies.rsi_macd.v3 import UserStrategy as V3
from backend_dev.tests.test_macd_dev import HOUR, START, candles, context, request
from trading_lab.interfaces.cli import load_request


def req(version, future=False):
    return request(future=future).model_copy(
        update={
            "strategy_id": "rsi_macd",
            "strategy_version": version,
            "stop_loss_pct": Decimal(5),
            "take_profit_pct": Decimal(10) if version == "v3" else None,
        }
    )


def strategy(cls):
    instance = cls(rsi_period=2, fast=2, slow=3, signal=2)

    class Feed:
        def __init__(self, values):
            self.values = iter(values)
            self.value = None

        def update(self, close):
            self.value = next(self.values)
            return self.value

    instance._rsi = Feed(list(map(Decimal, [50, 50, 50, 50, 37, 37, 71, 50, 50])))
    instance._macd = Feed(
        [MACDValue(Decimal(h), Decimal(0), Decimal(h)) for h in [-1, -1, 1, 1, 1, 1, -1, -1, -1]]
    )
    return instance


@pytest.mark.parametrize("cls", [V2, V3])
def test_inherited_signal_rules(cls):
    first, other = V1(), cls()
    for rsi in [37, 38, 50, 70, 71]:
        for hist in [-1, 0, 1]:
            value = MACDValue(Decimal(hist), Decimal(0), Decimal(hist))
            assert first._decide(Decimal(rsi), value, context([100])) == other._decide(
                Decimal(rsi), value, context([100])
            )


@pytest.mark.parametrize("cls,version", [(V2, "v2"), (V3, "v3")])
@pytest.mark.parametrize(
    "changes",
    [
        {"stop_loss_pct": None},
        {"stop_loss_pct": Decimal("NaN")},
        {"stop_loss_pct": Decimal(0)},
        {"strategy_version": "v1"},
        {"warmup_bars": 0},
    ],
)
def test_invalid_common_risk_settings(cls, version, changes):
    with pytest.raises(ValueError):
        cls(rsi_period=2, fast=2, slow=3, signal=2).validate_request(
            req(version).model_copy(update=changes)
        )


def test_v2_forbids_tp_and_v3_requires_tp():
    with pytest.raises(ValueError, match="forbids TP"):
        V2(rsi_period=2, fast=2, slow=3, signal=2).validate_request(
            req("v2").model_copy(update={"take_profit_pct": Decimal(10)})
        )
    with pytest.raises(ValueError, match="take_profit_pct"):
        V3(rsi_period=2, fast=2, slow=3, signal=2).validate_request(
            req("v3").model_copy(update={"take_profit_pct": None})
        )


@pytest.mark.parametrize("future", [False, True])
@pytest.mark.parametrize("cls,version", [(V2, "v2"), (V3, "v3")])
def test_sl_closes_and_reentry_is_not_locked(cls, version, future):
    data = list(candles([100, 100, 100, 100, 110, 110, 110, 90, 90]))
    data[5] = replace(data[5], low=Decimal(100))
    account, _, assumptions, _ = run_engine(req(version, future), data, strategy(cls))
    first = account.trades[0]
    assert first.exit_reason == "stop_loss"
    assert first.exit_time == START + 6 * HOUR
    assert abs(first.exit_price - Decimal("104.5")) < Decimal("1e-40")
    assert len(account.trades) >= 2
    assert account.trades[1].entry_time == START + 6 * HOUR
    assert any("RSI+MACD" in item for item in assumptions)


@pytest.mark.parametrize("future", [False, True])
def test_v3_tp_and_ambiguous_bar(future):
    data = list(candles([100, 100, 100, 100, 110, 110, 110, 90, 90]))
    data[5] = replace(data[5], high=Decimal(125))
    account, _, _, _ = run_engine(req("v3", future), data, strategy(V3))
    assert account.trades[0].exit_reason == "take_profit"
    data[5] = replace(data[5], low=Decimal(100))
    account, _, _, _ = run_engine(req("v3", future), data, strategy(V3))
    assert account.trades[0].exit_reason == "stop_loss"


@pytest.mark.parametrize("version,cls", [("v2", V2), ("v3", V3)])
def test_45_configs_per_version_and_runner_check(version, cls, monkeypatch):
    import backend_dev.run_backtest as runner

    monkeypatch.setattr(runner, "Settings", lambda: pytest.fail("Must not access DB"))
    paths = list((DEV_DIR / f"config/rsi_macd/{version}").rglob("*.yaml"))
    assert len(paths) == 45
    sls = set()
    for path in paths:
        configured = load_request(path)
        sls.add(configured.stop_loss_pct)
        cls(**configured.strategy_parameters).validate_request(configured)
        assert configured.take_profit_pct == (
            configured.stop_loss_pct * 2 if version == "v3" else None
        )
    assert sls == set(map(Decimal, range(2, 11)))
    assert main(["--config", str(paths[0]), "--check"]) == 0
