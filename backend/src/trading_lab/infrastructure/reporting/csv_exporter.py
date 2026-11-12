"""UTF-8 CSV output with headers even when there are no trades."""

import csv
import json
from datetime import date, datetime


def cell(value):
    if value is None:
        return "N/A"
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, default=str, ensure_ascii=False)
    if isinstance(value, (datetime, date)):
        value = value.isoformat()
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def export_csv(path, rows, headers):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: cell(row.get(key)) for key in headers})
