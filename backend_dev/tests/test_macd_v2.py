"""MACD SL version, shared fee math and isolated execution routing."""

import json
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from backend_dev.backtesting.engine import run_engine
from backend_dev.run_backtest import DEV_DIR, main
from backend_dev.strategies.macd.v1 import UserStrategy as MACDv1
from backend_dev.strategies.macd.v2 import UserStrategy as MACDv2
from backend_dev.tests.test_macd_dev import HOUR, START, candles, context, request
from trading_lab.backtesting.engine import run_engine as original_engine
from trading_lab.backtesting.portfolio import Portfolio
from trading_lab.domain.enums import DirectionMode
from trading_lab.interfaces.cli import load_request


def v2_request(future=False, sl="5"):
    return request(future=future).model_copy(
        update={
            "strategy_version": "v2",
            "stop_loss_pct": Decimal(sl),
        }
    )


@pytest.mark.parametrize("mode", list(DirectionMode))
def test_v2_rsi_free_signals_match_v1(mode):
    first, second = MACDv1(2, 3, 2), MACDv2(2, 3, 2)
    prices = [100, 100, 100, 100, 110, 110, 90, 90, 90]
    for end in range(1, len(prices) + 1):
        ctx = context(prices[:end], mode=mode)
        assert first.on_bar(ctx) == second.on_bar(ctx)


@pytest.mark.parametrize("future", [False, True])
def test_intrabar_stop_and_normal_costs(future):
    req = v2_request(future).model_copy(
        update={
            "fee_rate_open": Decimal("0.001"),
            "fee_rate_close": Decimal("0.001"),
            "slippage_bps": Decimal("5"),
        }
    )
    data = list(candles([100, 100, 100, 100, 110, 110, 90, 90, 90]))
    data[5] = replace(data[5], low=Decimal(100))
    account, _, assumptions, _ = run_engine(req, data, MACDv2(2, 3, 2))
    trade = account.trades[0]
    assert trade.exit_reason == "stop_loss" and not trade.liquidated
    assert trade.exit_time == START + 6 * HOUR
    expected = trade.entry_price * Decimal("0.95") * Decimal("0.9995")
    assert abs(trade.exit_price - expected) < Decimal("1e-40")
    expected_fees = trade.quantity * (trade.entry_price + trade.exit_price) * Decimal("0.001")
    assert abs(trade.fees - expected_fees) < Decimal("2e-12")
    assert any("MACD v2" in item for item in assumptions)
    assert not any("RSI" in item for item in assumptions)


def test_gap_stop_precedes_opposite_cross_order():
    data = candles([100, 100, 100, 100, 110, 110, 90, 90, 90])
    account, _, _, _ = run_engine(v2_request(True), data, MACDv2(2, 3, 2))
    first, second = account.trades
    assert first.exit_reason == "stop_loss" and first.exit_time == START + 6 * HOUR
    assert abs(first.exit_price - Decimal(90)) < Decimal("1e-40")
    assert second.position_side == "short" and second.entry_time == START + 7 * HOUR


def test_no_stop_hit_keeps_baseline_trade_sequence():
    data = candles([100, 100, 100, 100, 110, 110, 90, 90, 90])
    old, _, _, _ = original_engine(request(future=True), data, MACDv1(2, 3, 2))
    new, _, _, _ = run_engine(v2_request(True, sl="30"), data, MACDv2(2, 3, 2))
    assert new.trades == old.trades


def test_nominal_commission_does_not_multiply_leverage_twice():
    req = v2_request(True).model_copy(
        update={
            "leverage": Decimal(5),
            "fee_rate_open": Decimal("0.0005"),
            "fee_rate_close": Decimal("0.0005"),
        }
    )
    portfolio = Portfolio(req)
    portfolio.open("long", Decimal(100), START)
    quantity = portfolio.position.quantity
    portfolio.close(Decimal(100), START + HOUR)
    assert abs(portfolio.total_fees - quantity * 100 * Decimal("0.001")) < Decimal("2e-12")


@pytest.mark.parametrize(
    "changes",
    [
        {"stop_loss_pct": None},
        {"stop_loss_pct": Decimal(0)},
        {"stop_loss_pct": Decimal("NaN")},
        {"take_profit_pct": Decimal(10)},
        {"strategy_version": "v1"},
        {"warmup_bars": 0},
    ],
)
def test_invalid_version_sl_tp_or_warmup(changes):
    with pytest.raises(ValueError):
        MACDv2(2, 3, 2).validate_request(v2_request().model_copy(update=changes))


def test_all_45_configs_validate_and_preserve_v1_inputs():
    files = list((DEV_DIR / "config/macd/v2").rglob("*.yaml"))
    assert len(files) == 45
    observed = set()
    for path in files:
        req = load_request(path)
        MACDv2(**req.strategy_parameters).validate_request(req)
        observed.add((req.market_type.value, req.leverage, req.stop_loss_pct))
        assert req.take_profit_pct is None
        old_name = path.name.replace("macd_v2", "macd_v1").rsplit("_sl", 1)[0] + ".yaml"
        old_path = (
            DEV_DIR
            / "config/macd/v1"
            / path.relative_to(DEV_DIR / "config/macd/v2").parent
            / old_name
        )
        old = load_request(old_path)
        excluded = {"strategy_version", "stop_loss_pct"}
        assert req.model_dump(exclude=excluded) == old.model_dump(exclude=excluded)
    assert len(observed) == 45


def test_v2_runner_check_avoids_database(monkeypatch):
    import backend_dev.run_backtest as runner

    monkeypatch.setattr(runner, "Settings", lambda: pytest.fail("Must not access DB"))
    path = (
        DEV_DIR
        / "config/macd/v2/future/long_short/BTC_USDT_USDT/1h/2x/macd_v2_btc_future_1h_2x_sl5.yaml"
    )
    assert main(["--config", str(path), "--check"]) == 0


def test_read_only_service_and_parameter_report_path(tmp_path, monkeypatch, capsys):
    import backend_dev.backtesting.service as service
    import backend_dev.run_backtest as runner

    req = v2_request()
    data = candles([100, 100, 100, 100, 110, 110, 90, 90, 90])
    # No insert/update methods or run store: any accidental write would fail.
    saved = SimpleNamespace(exchange="binance", symbol="BTC/USDT", market_type=req.market_type)
    repository = SimpleNamespace(
        find_market=lambda *a: saved,
        iter_candles=lambda *a, **k: iter(data),
        iter_funding_rates=lambda *a, **k: iter(()),
    )

    @contextmanager
    def units():
        yield SimpleNamespace(data=repository)

    monkeypatch.setattr(service, "code_identity", lambda strategy: (None, "source"))
    strategy = MACDv2(2, 3, 2)
    result = service.run_backtest(req, strategy, units)
    assert result.request.strategy_id == "macd" and result.request.strategy_version == "v2"
    assert result.model_version == service.DEV_MODEL_VERSION
    config = tmp_path / "config.json"
    req = req.model_copy(update={"strategy_parameters": {"fast": 2, "slow": 3, "signal": 2}})
    config.write_text(req.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(runner, "DEV_DIR", tmp_path)
    monkeypatch.setattr(runner, "development_hash", lambda: "dev-source")
    monkeypatch.setattr(runner, "Settings", lambda: object())
    monkeypatch.setattr(
        runner, "build_engine", lambda settings: SimpleNamespace(dispose=lambda: None)
    )
    monkeypatch.setattr(runner, "build_session_factory", lambda engine: None)
    monkeypatch.setattr(runner, "data_unit_factory", lambda sessions: units)
    assert runner.main(["--config", str(config)]) == 0
    payload = json.loads(capsys.readouterr().out)
    directory = Path(payload["report_directory"])
    assert directory.is_relative_to(tmp_path / "reports/macd/v2")
    assert directory.name.endswith("-SL5-TPnone-MACD2-3-2")
    restored = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    assert restored["request"]["strategy_id"] == "macd"
    assert restored["data_quality"]["development_source_sha256"] == "dev-source"
