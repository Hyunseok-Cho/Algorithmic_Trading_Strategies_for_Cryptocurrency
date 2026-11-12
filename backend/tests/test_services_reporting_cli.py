import json
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from typer.testing import CliRunner

from tests.fixtures.fakes import MemoryData, MemoryRuns, MemoryState, memory_units
from tests.fixtures.scenarios import NoTrades, ScheduledStrategy, bars, market, request
from trading_lab.application.backtest_service import BacktestService
from trading_lab.application.dto import BacktestResult
from trading_lab.application.report_service import ReportService
from trading_lab.config import BACKEND_DIR
from trading_lab.domain.enums import DirectionMode, MarketType
from trading_lab.domain.exceptions import DataCoverageError
from trading_lab.infrastructure.database.dataframe import candles_frame
from trading_lab.interfaces.cli import app, load_request
from trading_lab.strategies.registry import STRATEGIES, StrategyNotImplemented, create_strategy


def fixture_result(strategy=None, *, prices=(100, 100, 110, 120)):
    state = MemoryState()
    data = MemoryData(state)
    saved_market = market()
    data.save_market(saved_market)
    data.upsert_candles(saved_market, "1h", bars(prices))
    runs = MemoryRuns()
    result = BacktestService(memory_units(state), runs).run(
        request(len(prices)), strategy=strategy or ScheduledStrategy()
    )
    return result, runs


def test_report_bundle_excel_json_agree_and_manifest_hashes(tmp_path):
    import hashlib

    result, runs = fixture_result()
    destination = ReportService(tmp_path, runs).export(result)
    assert set(path.name for path in destination.iterdir()) == {
        "report.xlsx",
        "summary.json",
        "trades.csv",
        "equity_curve.csv",
        "daily_statistics.csv",
        "manifest.json",
        "result.json",
    }
    workbook = load_workbook(destination / "report.xlsx", data_only=True)
    assert workbook.sheetnames == [
        "Summary",
        "Parameters",
        "Trades",
        "EquityCurve",
        "DailyStatistics",
        "DataQuality",
        "Assumptions",
    ]
    summary = json.loads((destination / "summary.json").read_text(encoding="utf-8"))
    excel = {row[0]: row[1] for row in workbook["Summary"].iter_rows(min_row=2, values_only=True)}
    assert Decimal(str(excel["ending_equity"])) == Decimal(summary["ending_equity"])
    assert excel["completed_trades"] == summary["completed_trades"] == 1
    assert workbook["Trades"].freeze_panes == "A2"
    workbook.close()
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    for filename, record in manifest["files"].items():
        assert record["sha256"] == hashlib.sha256((destination / filename).read_bytes()).hexdigest()
    assert runs.records[result.run_id]["status"] == "completed"
    assert runs.records[result.run_id]["report_path"] == destination


def test_empty_trade_report_has_headers_and_na_instead_of_infinity(tmp_path):
    result, _ = fixture_result(NoTrades())
    destination = ReportService(tmp_path).export(result)
    assert (destination / "trades.csv").read_text(encoding="utf-8-sig").startswith("trade_number,")
    payload = json.loads((destination / "summary.json").read_text(encoding="utf-8"))
    assert payload["profit_factor"] is None


def test_report_paths_group_by_strategy_symbol_timeframe_and_requested_utc_interval(tmp_path):
    result, _ = fixture_result()
    service = ReportService(tmp_path)
    first = service.export(result)
    assert first.relative_to(tmp_path).parts == (
        "fixture", "v1", "spot", "BTC_USDT", "1h", "1x",
        "2021-01-01T00-00-00Z - 2021-01-01T04-00-00Z",
    )
    original = (first / "manifest.json").read_bytes()
    second = service.export(result)
    assert second != first
    assert second.parent == first.parent
    assert second.name.startswith(first.name + "__")
    assert (first / "manifest.json").read_bytes() == original
    assert (second / "result.json").exists()


@pytest.mark.parametrize("mode", ["long_only", "short_only", "long_short"])
def test_future_report_layout(tmp_path, mode):
    result, _ = fixture_result()
    future_request = result.request.model_copy(update={
        "market_type": MarketType.PERPETUAL,
        "direction_mode": DirectionMode(mode),
        "symbol": "BTC/USDT:USDT", "leverage": Decimal("5.00"),
    })
    destination = ReportService(tmp_path).export(result.model_copy(update={"request": future_request}))
    assert destination.relative_to(tmp_path).parts[:-1] == (
        "fixture", "v1", "future", mode, "BTC_USDT_USDT", "1h", "5x",
    )


def test_report_path_components_cannot_escape_root_or_use_windows_devices(tmp_path):
    from trading_lab.application.report_service import report_component

    assert report_component("BTC/USDT:USDT") == "BTC_USDT_USDT"
    assert report_component("CON") == "_CON"
    assert report_component("..") == "%2E%2E"
    assert "\\" not in report_component("..\\outside")
    result, _ = fixture_result()
    result = result.model_copy(update={
        "request": result.request.model_copy(update={"strategy_id": "../../outside"})
    })
    assert ReportService(tmp_path).export(result).is_relative_to(tmp_path)


def test_json_roundtrip_reexport_preserves_numeric_excel_summary(tmp_path):
    original, _ = fixture_result()
    restored = BacktestResult.model_validate_json(original.model_dump_json())
    assert restored == original
    destination = ReportService(tmp_path).export(restored)
    workbook = load_workbook(destination / "report.xlsx", data_only=True)
    cells = {row[0].value: row[1] for row in workbook["Summary"].iter_rows(min_row=2)}
    assert cells["ending_equity"].data_type == "n"
    workbook.close()


def test_export_failure_is_recorded_without_changing_successful_backtest(tmp_path, monkeypatch):
    result, runs = fixture_result()

    def fail(*args):
        raise OSError("Synthetic disk failure")

    monkeypatch.setattr("trading_lab.application.report_service.export_excel", fail)
    with pytest.raises(OSError):
        ReportService(tmp_path, runs).export(result)
    assert runs.records[result.run_id]["status"] == "completed"
    assert runs.records[result.run_id]["report_error"]
    assert not list(tmp_path.rglob("manifest.json"))


def test_backtest_failure_is_recorded():
    state, runs = MemoryState(), MemoryRuns()
    MemoryData(state).save_market(market())
    with pytest.raises(DataCoverageError):
        BacktestService(memory_units(state), runs).run(request(), strategy=NoTrades())
    assert next(iter(runs.records.values()))["status"] == "failed"


def test_pandas_view_keeps_decimal_and_utc_index():
    frame = candles_frame(bars([100, 101]))
    assert str(frame.index.tz) == "UTC"
    assert isinstance(frame.iloc[0]["open"], Decimal)


def test_strategy_list_and_unimplemented_run_need_no_db(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "trading_lab.interfaces.cli.runtime", lambda: pytest.fail("Must not access DB")
    )
    runner = CliRunner()
    listing = runner.invoke(app, ["strategy", "list"])
    assert listing.exit_code == 0
    states = {item["id"]: item["implemented"] for item in json.loads(listing.stdout)}
    assert states == {"rsi": True, "macd": False, "rsi_macd": False}
    config = tmp_path / "request.json"
    config.write_text(
        request().model_copy(update={"strategy_id": "macd"}).model_dump_json(), encoding="utf-8"
    )
    execution = runner.invoke(app, ["backtest", "run", "--config", str(config)])
    assert execution.exit_code == 1
    assert "not implemented" in execution.output
    for info in STRATEGIES:
        if not info.implemented:
            with pytest.raises(StrategyNotImplemented):
                create_strategy(info.id, {})


def test_yaml_loader_preserves_exact_decimal_input(tmp_path):
    config = tmp_path / "config.yaml"
    values = request().model_dump(mode="json")
    import yaml

    config.write_text(yaml.safe_dump(values) + "\n", encoding="utf-8")
    loaded = load_request(config)
    assert loaded == request()


def test_unquoted_yaml_decimal_and_nonfinite_rejection(tmp_path):
    import re

    import yaml

    path = tmp_path / "request.yaml"
    content = yaml.safe_dump(request().model_dump(mode="json"))
    exact = "0.0001234567890123456789012345"
    path.write_text(
        re.sub(r"fee_rate_open:.*", f"fee_rate_open: {exact}", content), encoding="utf-8"
    )
    assert load_request(path).fee_rate_open == Decimal(exact)
    path.write_text(re.sub(r"fee_rate_open:.*", "fee_rate_open: .nan", content), encoding="utf-8")
    assert CliRunner().invoke(app, ["backtest", "run", "--config", str(path)]).exit_code == 1


def test_cli_help_and_api_placeholder():
    assert CliRunner().invoke(app, ["--help"]).exit_code == 0
    assert list((BACKEND_DIR / "src/trading_lab/interfaces/api").iterdir()) == [
        BACKEND_DIR / "src/trading_lab/interfaces/api/.gitkeep"
    ]
