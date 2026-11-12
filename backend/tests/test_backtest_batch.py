"""Batch matrix coverage, preservation, preflight and resumable CLI orchestration."""

import csv
import json
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from scripts import run_backtest_batch as batch

from tests.fixtures.fakes import MemoryData, MemoryState, memory_units
from tests.fixtures.scenarios import bars, market
from tests.test_services_reporting_cli import fixture_result
from trading_lab.application.report_service import ReportService


def test_complete_matrix_and_paired_ratio():
    requests = list(batch.matrix_requests())
    assert len(requests) == 858
    assert Counter(req.strategy_version for req in requests) == {"v1": 48, "v2": 405, "v3": 405}
    assert len({batch.config_path(Path("config"), req) for req in requests}) == 858
    assert Counter(req.symbol.split("/")[0] for req in requests) == {
        "BTC": 286, "ETH": 286, "SOL": 286,
    }
    spot = [req for req in requests if req.market_type.value == "spot"]
    assert len(spot) == 3 and all(req.strategy_version == "v1" for req in spot)
    for req in requests:
        assert req.start_time == batch.START and req.end_time == batch.END
        assert req.warmup_bars == 14 and req.timeframe == "1h"
        assert 1 <= req.leverage <= 5
        if req.strategy_version == "v3":
            assert req.take_profit_pct == 2 * req.stop_loss_pct
        if req.strategy_version != "v1":
            assert 2 <= req.stop_loss_pct <= 10


def test_generate_preserves_existing_files_and_refuses_changes(tmp_path, monkeypatch):
    samples = list(batch.matrix_requests())[:2]
    monkeypatch.setattr(batch, "matrix_requests", lambda: iter(samples))
    pairs = batch.generate(tmp_path)
    path, _ = pairs[0]
    path.write_text("# User note\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    content = path.read_bytes()
    batch.generate(tmp_path)
    assert path.read_bytes() == content
    values = yaml.safe_load(path.read_text(encoding="utf-8"))
    values["initial_capital"] = "2000"
    path.write_text(yaml.safe_dump(values), encoding="utf-8")
    with pytest.raises(ValueError, match="not overwritten"):
        batch.generate(tmp_path)
    assert batch.load_request(path).initial_capital == 2000


def test_discovery_and_plan_need_no_database(tmp_path, monkeypatch):
    samples = [req for req in batch.matrix_requests() if req.market_type.value == "spot"]
    monkeypatch.setattr(batch, "matrix_requests", lambda: iter(samples))
    batch.generate(tmp_path)
    values = samples[0].model_dump(mode="json")
    values["strategy_version"] = "v4"
    (tmp_path / "reserved.yaml").write_text(json.dumps(values), encoding="utf-8")
    jobs, skipped = batch.discover(tmp_path)
    assert len(jobs) == 3 and len(skipped) == 1
    jobs, _ = batch.discover(tmp_path, symbols=["ETH"])
    assert len(jobs) == 1 and jobs[0][1].symbol == "ETH/USDT"
    monkeypatch.setattr(batch, "runtime", lambda: pytest.fail("Must not access DB"))
    assert batch.main(["--config-root", str(tmp_path), "--plan"]) == 0


def synthetic_job(tmp_path):
    result, _ = fixture_result()
    req = result.request.model_copy(update={"strategy_id": "rsi"})
    path = tmp_path / "job.yaml"
    path.write_text(req.model_dump_json(), encoding="utf-8")
    return path, req, result


def test_preflight_checks_missing_data_before_execution(tmp_path, monkeypatch):
    path, req, _ = synthetic_job(tmp_path)
    state = MemoryState()
    data = MemoryData(state)
    saved = market()
    data.save_market(saved)
    data.upsert_candles(saved, "1h", bars([100] * 4))

    @contextmanager
    def runtime():
        yield None, memory_units(state), None

    monkeypatch.setattr(batch, "runtime", runtime)
    signatures = batch.preflight([(path, req)])
    assert len(signatures[batch.dataset_key(req)]) == 64
    later = req.model_copy(update={"end_time": req.end_time + batch.timeframe_delta("1h")})
    with pytest.raises(ValueError, match="preflight failed"):
        batch.preflight([(path, later)])


def test_resume_rerun_and_changed_data_or_missing_report(tmp_path, monkeypatch):
    path, req, result = synthetic_job(tmp_path)
    directory = tmp_path / "state"
    directory.mkdir()
    signatures = {batch.dataset_key(req): "data-one"}
    monkeypatch.setattr(batch, "code_identity", lambda strategy: (None, "source"))
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        assert command[:4] == [batch.sys.executable, "-m", "trading_lab.interfaces.cli", "backtest"]
        current = batch.load_request(Path(command[-1]))
        exported = result.model_copy(update={
            "request": current,
            "data_quality": {"data_sha256": signatures[batch.dataset_key(current)],
                             "source_sha256": "source"},
        })
        destination = ReportService(tmp_path / "reports").export(exported)
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "run_id": str(exported.run_id), "report_directory": str(destination),
            "summary": exported.model_dump(mode="json")["summary"],
        }), stderr="")

    monkeypatch.setattr(batch.subprocess, "run", execute)
    jobs = [(path, req)]
    assert batch.run_jobs(jobs, directory, signatures) == 0
    assert batch.run_jobs(jobs, directory, signatures) == 0
    assert len(calls) == 1  # Completed intact run is skipped.
    assert batch.run_jobs(jobs, directory, signatures, rerun=True) == 0
    assert len(calls) == 2
    signatures[batch.dataset_key(req)] = "data-two"
    batch.run_jobs(jobs, directory, signatures)
    assert len(calls) == 3
    record = json.loads((directory / "state.json").read_text(encoding="utf-8"))[str(path.resolve())]
    artifact = Path(record["report_directory"]) / "report.xlsx"
    assert artifact.is_relative_to(tmp_path)
    artifact.unlink()
    batch.run_jobs(jobs, directory, signatures)
    assert len(calls) == 4
    with (directory / "summary.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]["status"] == "succeeded"
    assert len(list((directory / "logs").glob("*.stdout.txt"))) == 4


def test_failures_retry_and_interrupt_is_checkpointed(tmp_path, monkeypatch):
    path, req, _ = synthetic_job(tmp_path)
    directory = tmp_path / "state"
    directory.mkdir()
    signatures = {batch.dataset_key(req): "data"}
    monkeypatch.setattr(batch, "code_identity", lambda strategy: (None, "source"))
    monkeypatch.setattr(batch.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stdout="", stderr="Synthetic failure"))
    assert batch.run_jobs([(path, req)], directory, signatures) == 1
    records = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    assert records[str(path.resolve())]["status"] == "failed"

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(batch.subprocess, "run", interrupt)
    with pytest.raises(KeyboardInterrupt):
        batch.run_jobs([(path, req)], directory, signatures)
    records = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    assert records[str(path.resolve())]["status"] == "interrupted"
