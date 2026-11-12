"""Version routing, historical compatibility and fail-fast placeholder behavior."""

import json
from importlib import import_module

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from tests.fixtures.scenarios import request
from tests.test_services_reporting_cli import fixture_result
from trading_lab.application.dto import BacktestRequest, BacktestResult
from trading_lab.application.report_service import ReportService
from trading_lab.interfaces.cli import app
from trading_lab.strategies.registry import StrategyNotImplemented, create_strategy
from trading_lab.strategies.RSI_MACD.RSI.strategy import UserStrategy


def test_legacy_configs_and_results_default_to_v1():
    payload = request().model_dump(mode="json")
    payload.pop("strategy_version")
    assert BacktestRequest.model_validate(payload).strategy_version == "v1"
    original, _ = fixture_result()
    payload = original.model_dump(mode="json")
    payload["request"].pop("strategy_version")
    restored = BacktestResult.model_validate(payload)
    assert restored.request.strategy_version == "v1"
    assert restored.summary == original.summary
    assert restored.trades == original.trades


def test_v1_uses_existing_strategy_without_parameter_changes():
    implicit = create_strategy("rsi", {})
    explicit = create_strategy("rsi", {}, version="v1")
    assert type(implicit) is type(explicit) is UserStrategy
    assert implicit.parameters == explicit.parameters == {
        "period": 14, "lower": "38", "upper": "70",
    }


@pytest.mark.parametrize("version", ["v4"])
def test_placeholders_fail_before_database_access(version, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "trading_lab.interfaces.cli.runtime", lambda: pytest.fail("Must not access DB")
    )
    with pytest.raises(StrategyNotImplemented, match=f"RSI {version} is not implemented"):
        create_strategy("rsi", {}, version=version)
    config = tmp_path / "request.json"
    config.write_text(request(strategy_id="rsi", strategy_version=version).model_dump_json(),
                      encoding="utf-8")
    outcome = CliRunner().invoke(app, ["backtest", "run", "--config", str(config)])
    assert outcome.exit_code == 1
    assert f"RSI {version} is not implemented" in outcome.output
    module = import_module(f"trading_lab.strategies.RSI_MACD.RSI.versions.{version}.strategy")
    with pytest.raises(NotImplementedError, match="placeholder"):
        module.UserStrategy()


def test_unknown_versions_are_rejected():
    with pytest.raises(ValidationError):
        request(strategy_version="v99")
    with pytest.raises(ValueError, match="Unknown version"):
        create_strategy("rsi", {}, version="v99")
    with pytest.raises(ValueError, match="Unknown version"):
        create_strategy("macd", {}, version="v2")


def test_listing_exposes_placeholder_status():
    output = CliRunner().invoke(app, ["strategy", "list"])
    assert output.exit_code == 0
    rsi = next(item for item in json.loads(output.stdout) if item["id"] == "rsi")
    assert {item["version"]: item["implemented"] for item in rsi["versions"]} == {
        "v1": True, "v2": True, "v3": True, "v4": False,
    }


def test_version_path_and_metadata(tmp_path):
    result, _ = fixture_result()
    service = ReportService(tmp_path)
    first = service.export(result)
    # Synthetic result: exercise export routing independently of backtest execution.
    second = service.export(result.model_copy(update={
        "request": result.request.model_copy(update={"strategy_version": "v2"})
    }))
    assert first.relative_to(tmp_path).parts[:2] == ("fixture", "v1")
    assert second.relative_to(tmp_path).parts[:2] == ("fixture", "v2")
    assert (first / "result.json").exists()
    stored = json.loads((second / "result.json").read_text(encoding="utf-8"))
    manifest = json.loads((second / "manifest.json").read_text(encoding="utf-8"))
    assert stored["request"]["strategy_version"] == "v2"
    assert manifest["parameters"]["strategy_version"] == "v2"
