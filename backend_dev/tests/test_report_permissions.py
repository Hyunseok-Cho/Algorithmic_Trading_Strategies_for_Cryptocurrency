"""Windows completed reports must inherit permissions instead of owner-only staging ACLs."""

import subprocess
import sys

import pytest
from backend_dev.backtesting.engine import run_engine
from backend_dev.reporting.service import ReportService
from backend_dev.strategies.macd.v3 import UserStrategy
from backend_dev.tests.test_macd_dev import candles
from backend_dev.tests.test_macd_v3 import v3_request
from trading_lab.application.dto import BacktestResult
from trading_lab.backtesting.metrics import calculate_metrics


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL regression")
def test_completed_bundle_inherits_output_parent_permissions(tmp_path):
    req = v3_request()
    data = candles([100, 100, 100, 100, 110, 110, 90, 90, 90])
    account, curve, assumptions, warnings = run_engine(req, data, UserStrategy(2, 3, 2))
    summary, daily = calculate_metrics(req, account, curve, data)
    result = BacktestResult(
        request=req,
        summary=summary,
        trades=tuple(account.trades),
        equity_curve=curve,
        daily_statistics=daily,
        data_quality={},
        assumptions=assumptions,
        warnings=warnings,
        order_count=account.order_count,
    )
    destination = ReportService(tmp_path / "reports").export(result)
    for path in (destination, destination / "report.xlsx"):
        acl = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=True)
        assert "(I)" in acl.stdout, "Completed report retained a protected staging ACL"
