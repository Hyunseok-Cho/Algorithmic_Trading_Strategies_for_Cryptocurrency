"""Sequential development YAML batch with checkpointing and a comparison CSV."""

# ruff: noqa: E402 -- standalone script bootstrap.

import argparse
import hashlib
import io
import json
import sys
from collections import Counter
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trading_lab.application.backtest_service import fingerprint
from trading_lab.backtesting.validation import validate_inputs
from trading_lab.config import Settings
from trading_lab.domain.timeframes import timeframe_delta
from trading_lab.infrastructure.database.engine import build_engine, build_session_factory
from trading_lab.infrastructure.database.unit_of_work import data_unit_factory
from trading_lab.infrastructure.reporting.csv_exporter import export_csv
from trading_lab.interfaces.cli import load_request

from backend_dev.run_backtest import DEV_DIR, development_hash
from backend_dev.run_backtest import main as execute

METRICS = (
    "ending_equity",
    "total_return_pct",
    "max_drawdown_pct",
    "profit_factor",
    "completed_trades",
    "win_rate_pct",
    "total_fees",
    "total_funding",
)
HEADERS = (
    "market",
    "direction",
    "leverage",
    "sl",
    "tp",
    "status",
    *METRICS,
    "stop_loss_exits",
    "take_profit_exits",
    "liquidation_exits",
    "run_id",
    "report_directory",
    "error",
)


def dataset_key(req):
    return (
        req.market_type,
        req.symbol,
        req.timeframe,
        req.start_time,
        req.end_time,
        req.warmup_bars,
    )


def data_signatures(jobs):
    engine = build_engine(Settings())
    signatures = {}
    try:
        units = data_unit_factory(build_session_factory(engine))
        for _, req in jobs:
            key = dataset_key(req)
            if key in signatures:
                continue
            with units() as unit:
                market = unit.data.find_market(req.exchange, req.market_type, req.symbol)
                if market is None:
                    raise ValueError(f"Missing stored market: {req.symbol}")
                first = req.start_time - req.warmup_bars * timeframe_delta(req.timeframe)
                candles = tuple(
                    unit.data.iter_candles(market, req.timeframe, start=first, end=req.end_time)
                )
                funding = (
                    tuple(
                        unit.data.iter_funding_rates(market, start=req.start_time, end=req.end_time)
                    )
                    if req.market_type.value == "perpetual"
                    else ()
                )
            validate_inputs(req, candles, funding)
            signatures[key] = fingerprint(candles, funding)
            print(f"Data OK: {req.symbol}, {len(candles)} candles", flush=True)
    finally:
        engine.dispose()
    return signatures


def save(directory, records):
    temp = directory / "state.json.tmp"
    temp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(directory / "state.json")
    rows = []
    for record in records.values():
        row = {key: record.get(key) for key in HEADERS}
        for key in ("leverage", "sl", "tp", *METRICS):
            if row[key] is not None:
                row[key] = Decimal(str(row[key]))
        rows.append(row)
    temp = directory / "summary.csv.tmp"
    export_csv(temp, rows, HEADERS)
    temp.replace(directory / "summary.csv")


def intact(record):
    if record.get("status") != "succeeded":
        return False
    try:
        directory = Path(record["report_directory"])
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        return (
            manifest["run_id"] == record["run_id"]
            and len(manifest["files"]) == 6
            and all(
                hashlib.sha256((directory / name).read_bytes()).hexdigest() == data["sha256"]
                for name, data in manifest["files"].items()
            )
        )
    except (OSError, KeyError, ValueError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", choices=("macd", "rsi_macd", "bollinger_mr"), default="macd")
    parser.add_argument("--version", choices=("v1", "v2", "v3"), default="v3")
    parser.add_argument("--exit-middle", choices=("dynamic", "fixed"), help="Bollinger v1 override")
    parser.add_argument("--rerun", action="store_true")
    args = parser.parse_args(argv)
    if args.exit_middle and (args.strategy, args.version) != ("bollinger_mr", "v1"):
        parser.error("--exit-middle requires bollinger_mr/v1")
    jobs = [
        (path, load_request(path))
        for path in (DEV_DIR / "config" / args.strategy / args.version).rglob("*.yaml")
    ]
    jobs.sort(
        key=lambda job: (
            job[1].market_type.value != "spot",
            job[1].leverage,
            job[1].stop_loss_pct or 0,
        )
    )
    if not jobs:
        raise ValueError("No YAML configurations found")
    signatures = data_signatures(jobs)
    source_hash = development_hash()
    batch_name = f"{args.strategy}_{args.version}"
    if args.exit_middle:
        batch_name += f"_{args.exit_middle}"
    directory = DEV_DIR / "reports/batches" / batch_name
    directory.mkdir(parents=True, exist_ok=True)
    state = directory / "state.json"
    records = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {}
    failed = 0
    for index, (path, req) in enumerate(jobs, 1):
        if development_hash() != source_hash:
            raise ValueError("Development code changed; restart the batch")
        identity_inputs = [req.model_dump(mode="json"), source_hash, signatures[dataset_key(req)]]
        if args.exit_middle:
            identity_inputs.append(args.exit_middle)
        identity = hashlib.sha256(json.dumps(identity_inputs, sort_keys=True).encode()).hexdigest()
        key = str(path)
        previous = records.get(key, {})
        if not args.rerun and previous.get("identity") == identity and intact(previous):
            print(f"[{index}/{len(jobs)}] SKIP {path.name}", flush=True)
            continue
        record = dict(
            identity=identity,
            status="running",
            market=req.market_type.value,
            direction=req.direction_mode.value,
            leverage=str(req.leverage),
            sl=str(req.stop_loss_pct) if req.stop_loss_pct is not None else None,
            tp=str(req.take_profit_pct) if req.take_profit_pct is not None else None,
        )
        records[key] = record
        save(directory, records)
        print(
            f"[{index}/{len(jobs)}] RUN {record['market']} {req.leverage}x "
            f"SL{record['sl']} TP{record['tp']}",
            flush=True,
        )
        captured = io.StringIO()
        try:
            command = ["--config", str(path)]
            if args.exit_middle:
                command.extend(("--exit-middle", args.exit_middle))
            with redirect_stdout(captured):
                execute(command)
            payload = json.loads(captured.getvalue())
            report = Path(payload["report_directory"])
            result = json.loads((report / "result.json").read_text(encoding="utf-8"))
            if (
                result["data_quality"]["data_sha256"] != signatures[dataset_key(req)]
                or result["data_quality"]["development_source_sha256"] != source_hash
            ):
                raise ValueError("Data or code changed during execution")
            record.update(
                status="succeeded",
                run_id=payload["run_id"],
                report_directory=str(report),
                **payload["summary"],
            )
            counts = Counter(trade["exit_reason"] for trade in result["trades"])
            for reason in ("stop_loss", "take_profit", "liquidation"):
                record[f"{reason}_exits"] = counts[reason]
            if not intact(record):
                raise ValueError("Report bundle is incomplete")
            print(
                f"  return={record['total_return_pct']}%, TP={record['take_profit_exits']}, "
                f"SL={record['stop_loss_exits']}",
                flush=True,
            )
        except KeyboardInterrupt:
            record["status"] = "interrupted"
            save(directory, records)
            raise
        except Exception as exc:
            record.update(status="failed", error=type(exc).__name__)
            failed += 1
            print(f"  FAILED: {type(exc).__name__}", flush=True)
        (directory / f"{index:02}.stdout.json").write_text(captured.getvalue(), encoding="utf-8")
        save(directory, records)
    print(
        f"Completed: {sum(r['status'] == 'succeeded' for r in records.values())}/{len(jobs)}, "
        f"failures this invocation={failed}. CSV: {directory / 'summary.csv'}",
        flush=True,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted; run the same command to resume.", file=sys.stderr)
        raise SystemExit(130) from None
