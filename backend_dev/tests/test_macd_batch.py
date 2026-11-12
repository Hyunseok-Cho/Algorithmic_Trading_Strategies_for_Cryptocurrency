"""Development batch checkpoint/resume uses isolated synthetic report bundles."""

import json

import pytest
from backend_dev import run_all as batch
from backend_dev.backtesting.engine import run_engine
from backend_dev.strategies.macd.v3 import UserStrategy
from backend_dev.tests.test_macd_dev import candles
from backend_dev.tests.test_macd_v3 import v3_request
from trading_lab.application.dto import BacktestResult
from trading_lab.application.report_service import ReportService
from trading_lab.backtesting.metrics import calculate_metrics


def setup_batch(tmp_path, monkeypatch):
    req = v3_request()
    source = tmp_path / "config/macd/v3/job.yaml"
    source.parent.mkdir(parents=True)
    source.write_text(req.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(batch, "DEV_DIR", tmp_path)
    monkeypatch.setattr(batch, "development_hash", lambda: "development")
    monkeypatch.setattr(batch, "data_signatures", lambda jobs: {batch.dataset_key(req): "data"})
    return req


def test_batch_resume_and_integrity(tmp_path, monkeypatch):
    req = setup_batch(tmp_path, monkeypatch)
    data = candles([100, 100, 100, 100, 110, 110, 90, 90, 90])
    portfolio, curve, assumptions, warnings = run_engine(req, data, UserStrategy(2, 3, 2))
    summary, daily = calculate_metrics(req, portfolio, curve, data)
    result = BacktestResult(
        request=req,
        summary=summary,
        trades=tuple(portfolio.trades),
        equity_curve=curve,
        daily_statistics=daily,
        assumptions=assumptions,
        warnings=warnings,
        order_count=portfolio.order_count,
        data_quality={"data_sha256": "data", "development_source_sha256": "development"},
    )
    calls = []

    def execute(args):
        calls.append(args)
        directory = ReportService(tmp_path / "reports").export(result)
        print(
            json.dumps(
                {
                    "run_id": str(result.run_id),
                    "report_directory": str(directory),
                    "summary": result.model_dump(mode="json")["summary"],
                }
            )
        )

    monkeypatch.setattr(batch, "execute", execute)
    assert batch.main(["--version", "v3"]) == 0
    assert batch.main(["--version", "v3"]) == 0
    assert len(calls) == 1
    records = json.loads(
        (tmp_path / "reports/batches/macd_v3/state.json").read_text(encoding="utf-8")
    )
    record = next(iter(records.values()))
    assert record["status"] == "succeeded"
    assert batch.intact(record)
    assert record["stop_loss_exits"] >= 1
    assert batch.main(["--version", "v3", "--rerun"]) == 0
    assert len(calls) == 2


def test_batch_failure_and_interrupt_are_recorded(tmp_path, monkeypatch):
    setup_batch(tmp_path, monkeypatch)

    def fail(args):
        raise ValueError("Synthetic failure")

    monkeypatch.setattr(batch, "execute", fail)
    assert batch.main(["--version", "v3"]) == 1
    path = tmp_path / "reports/batches/macd_v3/state.json"
    assert next(iter(json.loads(path.read_text(encoding="utf-8")).values()))["status"] == "failed"

    def interrupt(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(batch, "execute", interrupt)
    with pytest.raises(KeyboardInterrupt):
        batch.main(["--version", "v3"])
    assert (
        next(iter(json.loads(path.read_text(encoding="utf-8")).values()))["status"] == "interrupted"
    )
