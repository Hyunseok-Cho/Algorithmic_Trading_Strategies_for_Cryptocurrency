"""Exact JSON serialization: Decimal values are strings, never NaN/Infinity."""

import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


def default(value):
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def export_json(path, value):
    path.write_text(
        json.dumps(value, default=default, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
        newline="\n",
    )
