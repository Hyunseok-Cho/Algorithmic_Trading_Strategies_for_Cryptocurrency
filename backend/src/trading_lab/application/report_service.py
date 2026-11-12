"""Export one immutable result to a complete, self-contained report directory."""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote
from uuid import uuid4

from trading_lab.application.dto import EquityPoint, Trade
from trading_lab.domain.enums import MarketType
from trading_lab.infrastructure.reporting.csv_exporter import export_csv
from trading_lab.infrastructure.reporting.excel_exporter import export_excel
from trading_lab.infrastructure.reporting.json_exporter import export_json


def report_component(value):
    """Keep unified symbols readable without allowing paths or Windows device names."""
    name = quote(value, safe="-_").replace(".", "%2E")
    name = name.replace("%2F", "_").replace("%3A", "_")
    if name.upper() in {"CON", "PRN", "AUX", "NUL"} or name.upper() in {
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
    }:
        name = "_" + name
    return name


def parameter_label(value):
    """Canonical numeric labels, preserving decimals and distinguishing unset values."""
    if value is None:
        return "none"
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return report_component(str(value))
    if not number.is_finite():
        raise ValueError("Report parameters must be finite")
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def report_name(result):
    request = result.request
    start = request.start_time.astimezone(UTC)
    end = request.end_time.astimezone(UTC)
    if request.strategy_id != "rsi" or request.strategy_version == "v1":
        return f"{start:%Y-%m-%dT%H-%M-%SZ} - {end:%Y-%m-%dT%H-%M-%SZ}"
    # Actual instantiated parameters take precedence over requested/defaulted inputs.
    parameters = {
        **request.strategy_parameters,
        **result.data_quality.get("strategy_effective_parameters", {}),
    }
    return (
        f"{start:%Y-%m-%dT%H%MZ}-{end:%Y-%m-%dT%H%MZ}"
        f"-SL{parameter_label(request.stop_loss_pct)}"
        f"-TP{parameter_label(request.take_profit_pct)}"
        f"-P{parameter_label(parameters.get('period', 'unknown'))}"
        f"-L{parameter_label(parameters.get('lower', 'unknown'))}"
        f"-U{parameter_label(parameters.get('upper', 'unknown'))}"
    )


class ReportService:
    def __init__(self, output_root, run_store=None):
        self.root = Path(output_root).resolve()
        self._runs = run_store

    def export(self, result):
        try:
            destination = self._export(result)
        except Exception as exc:
            if self._runs:
                try:
                    self._runs.report_status(
                        result.run_id, error=f"{type(exc).__name__}: export failed"
                    )
                except Exception:
                    exc.add_note("Could not persist report failure status")
            raise
        if self._runs:
            self._runs.report_status(result.run_id, path=destination)
        return destination

    def _export(self, result):
        request = result.request
        parent = (
            self.root / report_component(request.strategy_id)
            / report_component(request.strategy_version)
        )
        if request.market_type is MarketType.SPOT:
            parent /= "spot"
        else:
            parent = parent / "future" / request.direction_mode.value
        leverage = format(request.leverage, "f")
        if "." in leverage:
            leverage = leverage.rstrip("0").rstrip(".")
        parent = (
            parent / report_component(request.symbol)
            / report_component(request.timeframe) / f"{leverage}x"
        )
        parent.mkdir(parents=True, exist_ok=True)
        interval = report_name(result)
        destination = parent / interval
        while destination.exists():
            destination = parent / f"{interval}__{uuid4().hex[:8]}"
        trades = [trade.model_dump() for trade in result.trades]
        curve = [point.model_dump() for point in result.equity_curve]
        daily = list(result.daily_statistics)
        trade_headers = list(Trade.model_fields)
        equity_headers = list(EquityPoint.model_fields)
        daily_headers = [
            "date",
            "opening_equity",
            "ending_equity",
            "pnl",
            "return_pct",
            "completed_trades",
        ]

        def pairs(values):
            return [{"parameter": key, "value": value} for key, value in values.items()]

        sheets = {
            "Summary": (["parameter", "value"], pairs(result.summary)),
            "Parameters": (["parameter", "value"], pairs(result.request.model_dump())),
            "Trades": (trade_headers, trades),
            "EquityCurve": (equity_headers, curve),
            "DailyStatistics": (daily_headers, daily),
            "DataQuality": (["parameter", "value"], pairs(result.data_quality)),
            "Assumptions": (
                ["kind", "description"],
                [{"kind": "assumption", "description": value} for value in result.assumptions]
                + [{"kind": "warning", "description": value} for value in result.warnings],
            ),
        }
        # A generated temporary directory contains only this export's staging files.
        with TemporaryDirectory(prefix=".export_", dir=parent) as temporary:
            staging = Path(temporary) / "payload"
            staging.mkdir()
            export_json(staging / "summary.json", {"run_id": result.run_id, **result.summary})
            export_json(staging / "result.json", result.model_dump(mode="json"))
            export_csv(staging / "trades.csv", trades, trade_headers)
            export_csv(staging / "equity_curve.csv", curve, equity_headers)
            export_csv(staging / "daily_statistics.csv", daily, daily_headers)
            export_excel(staging / "report.xlsx", sheets)
            files = {
                path.name: {
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                }
                for path in staging.iterdir()
            }
            export_json(
                staging / "manifest.json",
                {
                    "run_id": result.run_id,
                    "generated_at": datetime.now(UTC),
                    "code_revision": result.code_revision,
                    "model_version": result.model_version,
                    "data_quality": result.data_quality,
                    "parameters": result.request.model_dump(mode="json"),
                    "assumptions": result.assumptions,
                    "warnings": result.warnings,
                    "files": files,
                    "metric_policy": "UTC daily returns, 365 days/year, zero risk-free rate; see docs/metrics_definitions.md",
                    "excel_precision": "Excel numeric cells have ~15 significant digits; JSON/CSV preserve Decimal values",
                },
            )
            staging.rename(destination)
        return destination
