"""Same workbook layout, counting append rows instead of scanning cells per row."""

from decimal import Decimal

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from trading_lab.infrastructure.reporting.csv_exporter import cell


def export_excel(path, sheets):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, (headers, rows) in sheets.items():
        sheet = workbook.create_sheet(name)
        sheet.append(headers)
        for row_number, row in enumerate(rows, start=2):
            if row_number > 1048576:
                raise ValueError("Report exceeds Excel's row limit; shorten the experiment")
            sheet.append(
                [
                    float(value) if isinstance(value, Decimal) else cell(value)
                    for value in (row.get(key) for key in headers)
                ]
            )
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for header in sheet[1]:
            header.font = Font(bold=True, color="FFFFFF")
            header.fill = PatternFill("solid", fgColor="17365D")
        for index, key in enumerate(headers, 1):
            width = min(65, max(18, len(key) + 2))
            sheet.column_dimensions[get_column_letter(index)].width = width
            for row in sheet.iter_rows(min_row=2, min_col=index, max_col=index):
                item = row[0]
                if isinstance(item.value, (int, float)) and not isinstance(item.value, bool):
                    item.number_format = '0.0000"%"' if key.endswith("_pct") else "#,##0.000000"
        if name == "Summary":
            for row in sheet.iter_rows(min_row=2):
                if str(row[0].value).endswith("_pct"):
                    row[1].number_format = '0.0000"%"'
    equity = workbook["EquityCurve"]
    if equity.max_row > 1:
        chart = LineChart()
        chart.title, chart.y_axis.title, chart.x_axis.title = (
            "Equity (UTC)",
            "USDT",
            "UTC timestamp",
        )
        chart.add_data(
            Reference(equity, min_col=2, min_row=1, max_row=equity.max_row), titles_from_data=True
        )
        chart.set_categories(Reference(equity, min_col=1, min_row=2, max_row=equity.max_row))
        workbook["Summary"].add_chart(chart, "D2")
    workbook.save(path)
