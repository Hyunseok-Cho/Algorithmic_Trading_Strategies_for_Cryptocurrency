"""The faster row counter preserves workbook content, formatting and charts."""

from copy import copy
from decimal import Decimal

from backend_dev.reporting.excel import export_excel
from openpyxl import load_workbook
from trading_lab.infrastructure.reporting.excel_exporter import export_excel as baseline_export


def test_fast_export_preserves_existing_layout(tmp_path):
    sheets = {
        "Summary": (
            ["parameter", "value"],
            [
                {"parameter": "total_return_pct", "value": Decimal("-5.25")},
                {"parameter": "ending_equity", "value": Decimal("947.5")},
            ],
        ),
        "EquityCurve": (
            ["time", "equity"],
            [
                {"time": "2024-01-01T00:00:00Z", "equity": Decimal("1000")},
                {"time": "2024-01-02T00:00:00Z", "equity": Decimal("947.5")},
            ],
        ),
        "Trades": (["net_pnl", "note"], [{"net_pnl": Decimal("-52.5"), "note": "=bad"}]),
    }
    baseline_export(tmp_path / "old.xlsx", sheets)
    export_excel(tmp_path / "new.xlsx", sheets)
    old = load_workbook(tmp_path / "old.xlsx")
    new = load_workbook(tmp_path / "new.xlsx")
    assert old.sheetnames == new.sheetnames
    for name in old.sheetnames:
        a, b = old[name], new[name]
        assert a.freeze_panes == b.freeze_panes
        assert a.auto_filter.ref == b.auto_filter.ref
        assert a.max_row == b.max_row
        assert len(a._charts) == len(b._charts)
        for row_a, row_b in zip(a.iter_rows(), b.iter_rows(), strict=True):
            for x, y in zip(row_a, row_b, strict=True):
                assert (x.value, x.number_format, copy(x.font), copy(x.fill)) == (
                    y.value,
                    y.number_format,
                    copy(y.font),
                    copy(y.fill),
                )
    old.close()
    new.close()
