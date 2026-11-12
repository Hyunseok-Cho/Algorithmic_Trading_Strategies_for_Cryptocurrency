"""MACD v3 risk routing, paired configs and preservation of v2 behavior."""

from dataclasses import replace
from decimal import Decimal

import pytest
from backend_dev.backtesting.engine import run_engine
from backend_dev.run_backtest import DEV_DIR, main
from backend_dev.strategies.macd.v2 import UserStrategy as MACDv2
from backend_dev.strategies.macd.v3 import UserStrategy as MACDv3
from backend_dev.tests.test_macd_dev import HOUR, START, candles
from backend_dev.tests.test_macd_v2 import v2_request
from trading_lab.interfaces.cli import load_request


def v3_request(future=False, sl="5", tp="10"):
    return v2_request(future, sl).model_copy(
        update={
            "strategy_version": "v3",
            "take_profit_pct": Decimal(tp),
        }
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"stop_loss_pct": None},
        {"take_profit_pct": None},
        {"take_profit_pct": Decimal("NaN")},
        {"take_profit_pct": Decimal(0)},
        {"take_profit_pct": Decimal(100)},
        {"strategy_version": "v2"},
    ],
)
def test_invalid_v3_settings(changes):
    with pytest.raises(ValueError):
        MACDv3(2, 3, 2).validate_request(v3_request().model_copy(update=changes))


@pytest.mark.parametrize("future", [False, True])
def test_tp_executes_and_pays_costs(future):
    data = list(candles([100, 100, 100, 100, 110, 110, 90, 90, 90]))
    data[5] = replace(data[5], high=Decimal(130))
    req = v3_request(future).model_copy(
        update={
            "fee_rate_open": Decimal("0.001"),
            "fee_rate_close": Decimal("0.001"),
            "slippage_bps": Decimal(5),
        }
    )
    account, _, assumptions, _ = run_engine(req, data, MACDv3(2, 3, 2))
    first = account.trades[0]
    assert first.exit_reason == "take_profit" and first.exit_time == START + 6 * HOUR
    expected = first.entry_price * Decimal("1.1") * Decimal("0.9995")
    assert abs(first.exit_price - expected) < Decimal("1e-40")
    assert first.fees > 0 and first.net_pnl < first.gross_pnl
    assert any("MACD v3 adds fixed TP" in item for item in assumptions)


def test_unknown_intrabar_order_is_adverse_first():
    data = list(candles([100, 100, 100, 100, 110, 110, 90, 90, 90]))
    data[5] = replace(data[5], high=Decimal(130), low=Decimal(100))
    account, _, _, _ = run_engine(v3_request(True), data, MACDv3(2, 3, 2))
    assert account.trades[0].exit_reason == "stop_loss"


def test_favorable_opening_gap_tp_precedes_later_stop():
    data = list(candles([100, 100, 100, 100, 110, 110, 125, 125, 125]))
    data[6] = replace(data[6], low=Decimal(90))
    account, _, _, _ = run_engine(v3_request(), data, MACDv3(2, 3, 2))
    assert account.trades[0].exit_reason == "take_profit"
    assert account.trades[0].exit_time == START + 6 * HOUR
    assert account.trades[0].exit_price == 125


def test_unreached_tp_preserves_v2_trades():
    data = candles([100, 100, 100, 100, 110, 110, 90, 90, 90])
    second, _, _, _ = run_engine(v2_request(True), data, MACDv2(2, 3, 2))
    third, _, _, _ = run_engine(v3_request(True, tp="90"), data, MACDv3(2, 3, 2))
    assert second.trades == third.trades


def test_all_45_yaml_pairs_change_only_version_and_tp():
    paths = list((DEV_DIR / "config/macd/v3").rglob("*.yaml"))
    assert len(paths) == 45
    for path in paths:
        req = load_request(path)
        MACDv3(**req.strategy_parameters).validate_request(req)
        assert req.take_profit_pct == 2 * req.stop_loss_pct
        assert 2 <= req.stop_loss_pct <= 10
        old_name = path.stem.rsplit("_tp", 1)[0].replace("macd_v3", "macd_v2") + ".yaml"
        relative = path.relative_to(DEV_DIR / "config/macd/v3")
        old = load_request(DEV_DIR / "config/macd/v2" / relative.parent / old_name)
        exclude = {"strategy_version", "take_profit_pct"}
        assert req.model_dump(exclude=exclude) == old.model_dump(exclude=exclude)


def test_v3_check_does_not_access_db(monkeypatch):
    import backend_dev.run_backtest as runner

    monkeypatch.setattr(runner, "Settings", lambda: pytest.fail("Must not access DB"))
    path = (
        DEV_DIR
        / "config/macd/v3/future/long_short/BTC_USDT_USDT/1h/2x/macd_v3_btc_future_1h_2x_sl5_tp10.yaml"
    )
    assert main(["--config", str(path), "--check"]) == 0
