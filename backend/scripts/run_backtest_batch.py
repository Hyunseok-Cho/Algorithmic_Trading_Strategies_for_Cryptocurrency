"""Generate the RSI matrix and sequentially run YAMLs with resumable records.

No network downloads are performed here. Sync candles explicitly first.
Run with the backend venv: python scripts/run_backtest_batch.py --help
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import yaml

from trading_lab import MODEL_VERSION
from trading_lab.application.backtest_service import code_identity, fingerprint
from trading_lab.application.dto import BacktestRequest
from trading_lab.application.market_data_service import MarketDataService
from trading_lab.config import BACKEND_DIR
from trading_lab.domain.enums import MarketType
from trading_lab.domain.exceptions import DataCoverageError
from trading_lab.domain.timeframes import CandleRange, timeframe_delta
from trading_lab.infrastructure.reporting.csv_exporter import export_csv
from trading_lab.interfaces.cli import load_request, runtime
from trading_lab.strategies.registry import create_strategy, strategy_versions

DEFAULT_ROOT = BACKEND_DIR / "config/batches/20240101_20261031/rsi"
DEFAULT_STATE = BACKEND_DIR / "reports/batches/rsi_20240101_20261031"
START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2026, 11, 1, tzinfo=UTC)  # Includes all of October 31, UTC.
COINS = ("BTC", "ETH", "SOL")
DIRECTIONS = ("long_only", "short_only", "long_short")
METRICS = ("ending_equity", "total_return_pct", "max_drawdown_pct", "completed_trades",
           "win_rate_pct", "profit_factor", "total_fees", "total_funding")
HEADERS = ("config", "version", "market", "symbol", "direction", "leverage", "sl", "tp",
           "status", "run_id", *METRICS, "stop_loss_exits", "take_profit_exits",
           "liquidation_exits", "report_directory", "error")


def now():
    return datetime.now(UTC).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def matrix_requests():
    """48 v1 + 405 v2 + 405 v3. TP is paired with SL, never a Cartesian grid."""
    for version in ("v1", "v2", "v3"):
        if not any(v.version == version and v.implemented for v in strategy_versions("rsi")):
            continue
        for coin in COINS:
            common = dict(
                exchange="binance", strategy_id="rsi", strategy_version=version,
                timeframe="1h", start_time=START, end_time=END,
                strategy_parameters={"period": 14, "lower": "38", "upper": "70"},
                initial_capital="1000", allocation_pct="100", warmup_bars=14,
                slippage_bps="5", close_open_position_at_end=True,
            )
            if version == "v1":
                yield BacktestRequest(**common, market_type="spot", symbol=f"{coin}/USDT",
                                      fee_rate_open="0.001", fee_rate_close="0.001")
            for mode in DIRECTIONS:
                for leverage in range(1, 6):
                    for sl in ([None] if version == "v1" else range(2, 11)):
                        yield BacktestRequest(
                            **common, market_type="perpetual", symbol=f"{coin}/USDT:USDT",
                            direction_mode=mode, leverage=str(leverage), funding_mode="assume_zero",
                            fee_rate_open="0.0005", fee_rate_close="0.0005",
                            stop_loss_pct=str(sl) if sl is not None else None,
                            take_profit_pct=str(2 * sl) if version == "v3" else None,
                        )


def config_path(root, request):
    parent = root / request.strategy_version
    parent = parent / "spot" if request.market_type is MarketType.SPOT else (
        parent / "future" / request.direction_mode.value
    )
    symbol = request.symbol.replace("/", "_").replace(":", "_")
    parent = parent / symbol / request.timeframe / f"{request.leverage}x"
    name = f"rsi_{request.strategy_version}"
    if request.strategy_version != "v1":
        name += f"_SL{request.stop_loss_pct}_TP{request.take_profit_pct or 'none'}"
    return parent / f"{name}.yaml"


def generate(root):
    pairs = [(config_path(root, req), req) for req in matrix_requests()]
    # Verify all existing files before writing; never overwrite user experiments.
    for path, req in pairs:
        if path.exists() and load_request(path) != req:
            raise ValueError(f"Existing configuration differs; not overwritten: {path}")
    created = 0
    for path, req in pairs:
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write("# Batch 20240101_20261031. Fixed research assumptions; not optimized.\n")
            yaml.safe_dump(req.model_dump(mode="json"), stream, sort_keys=False, allow_unicode=True)
        created += 1
    print(f"YAMLs: {len(pairs)} total, {created} created, {len(pairs) - created} retained.")
    return pairs


def discover(root, versions=(), symbols=(), market=None):
    jobs, skipped = [], []
    for path in sorted({*root.rglob("*.yaml"), *root.rglob("*.yml")}):
        req = load_request(path)
        if versions and req.strategy_version not in versions:
            continue
        if symbols and req.symbol.split("/")[0] not in symbols:
            continue
        if market and req.market_type.value != market:
            continue
        info = next((v for v in strategy_versions(req.strategy_id)
                     if v.version == req.strategy_version), None)
        if info is None or not info.implemented:
            skipped.append(str(path))
            continue
        strategy = create_strategy(req.strategy_id, req.strategy_parameters,
                                   version=req.strategy_version)
        if hasattr(strategy, "validate_request"):
            strategy.validate_request(req)
        jobs.append((path, req))
    jobs.sort(key=lambda job: (
        int(job[1].strategy_version[1:]), job[1].market_type is MarketType.PERPETUAL,
        job[1].symbol, job[1].direction_mode.value, job[1].leverage,
        job[1].stop_loss_pct or 0, job[1].take_profit_pct or 0, str(job[0]),
    ))
    return jobs, skipped


def dataset_key(req):
    return (req.exchange, req.market_type, req.symbol, req.timeframe,
            req.start_time, req.end_time, req.warmup_bars)


def preflight(jobs):
    """Check each dataset once; hash actual prices/funding for safe resume."""
    signatures, missing = {}, []
    with runtime() as (_, units, _):
        service = MarketDataService(units)
        for _, req in jobs:
            key = dataset_key(req)
            if key in signatures:
                continue
            first = req.start_time - req.warmup_bars * timeframe_delta(req.timeframe)
            period = CandleRange(first, req.end_time, req.timeframe)
            try:
                coverage = service.status(req.exchange, req.market_type, req.symbol, period)
                if not coverage["complete"]:
                    raise ValueError(json.dumps(coverage, default=str))
                with units() as unit:
                    market = unit.data.find_market(req.exchange, req.market_type, req.symbol)
                    candles = tuple(unit.data.iter_candles(
                        market, req.timeframe, start=first, end=req.end_time))
                    funding = tuple(unit.data.iter_funding_rates(
                        market, start=req.start_time, end=req.end_time
                    )) if req.market_type is MarketType.PERPETUAL else ()
                signatures[key] = fingerprint(candles, funding)
                print(f"Data OK: {req.market_type.value} {req.symbol} {len(candles)} candles",
                      flush=True)
            except (ValueError, DataCoverageError) as exc:
                signatures[key] = None
                missing.append(f"{req.market_type.value} {req.symbol}: {exc}")
    if missing:
        raise ValueError("Data preflight failed; sync before running:\n" + "\n".join(missing))
    return signatures


def save_records(directory, records):
    """Atomic checkpoint plus a compact Excel-friendly cross-experiment CSV."""
    temporary = directory / "state.json.tmp"
    temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(directory / "state.json")
    rows = []
    for record in records.values():
        row = {key: record.get(key) for key in HEADERS}
        for key in (*METRICS, "leverage", "sl", "tp"):
            if row.get(key) is not None:
                row[key] = Decimal(str(row[key]))
        rows.append(row)
    temporary = directory / "summary.csv.tmp"
    export_csv(temporary, rows, HEADERS)
    temporary.replace(directory / "summary.csv")


def report_intact(record):
    if record.get("status") != "succeeded":
        return False
    try:
        directory = Path(record["report_directory"])
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest["run_id"] != record["run_id"]:
            return False
        if set(manifest["files"]) != {
            "result.json", "summary.json", "report.xlsx", "trades.csv",
            "equity_curve.csv", "daily_statistics.csv",
        }:
            return False
        return all(hashlib.sha256((directory / name).read_bytes()).hexdigest() == info["sha256"]
                   for name, info in manifest["files"].items())
    except (OSError, KeyError, ValueError):
        return False


@contextmanager
def batch_lock(directory):
    """OS lock is released on interruption; no stale lock deletion is required."""
    with (directory / ".batch.lock").open("a+b") as stream:
        stream.seek(0)
        stream.write(b"1")
        stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("Another batch is already using this state directory") from None
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def run_jobs(jobs, directory, signatures, *, limit=None, rerun=False):
    state_path = directory / "state.json"
    records = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    code_hashes, completed, skipped, failed = {}, 0, 0, 0
    for index, (path, req) in enumerate(jobs, 1):
        version_key = (req.strategy_id, req.strategy_version)
        if version_key not in code_hashes:
            strategy = create_strategy(req.strategy_id, req.strategy_parameters,
                                       version=req.strategy_version)
            code_hashes[version_key] = code_identity(strategy)[1]
        code_hash = code_hashes[version_key]
        data_hash = signatures[dataset_key(req)]
        identity = digest([req.model_dump(mode="json"), MODEL_VERSION, code_hash, data_hash])
        key = str(path.resolve())
        previous = records.get(key, {})
        if not rerun and previous.get("identity") == identity and report_intact(previous):
            skipped += 1
            print(f"[{index}/{len(jobs)}] SKIP completed: {path.name}", flush=True)
            continue
        if limit is not None and completed + failed >= limit:
            break
        record = dict(config=key, identity=identity, version=req.strategy_version,
                      market=req.market_type.value, symbol=req.symbol,
                      direction=req.direction_mode.value, leverage=str(req.leverage),
                      sl=str(req.stop_loss_pct) if req.stop_loss_pct is not None else None,
                      tp=str(req.take_profit_pct) if req.take_profit_pct is not None else None,
                      status="running", started_at=now())
        records[key] = record
        save_records(directory, records)
        print(f"[{index}/{len(jobs)}] RUN {req.strategy_version} {req.symbol} "
              f"{req.direction_mode.value} {req.leverage}x SL={record['sl']} TP={record['tp']}",
              flush=True)
        try:
            if load_request(path) != req:
                raise ValueError("YAML changed after planning; restart the batch")
            process = subprocess.run(
                [sys.executable, "-m", "trading_lab.interfaces.cli", "backtest", "run",
                 "--config", str(path)], cwd=BACKEND_DIR, capture_output=True,
                text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"}, check=False,
            )
            log = directory / "logs" / f"{index:04}_{identity[:12]}_{uuid4().hex[:8]}"
            log.parent.mkdir(exist_ok=True)
            log.with_suffix(".stdout.txt").write_text(process.stdout, encoding="utf-8")
            log.with_suffix(".stderr.txt").write_text(process.stderr, encoding="utf-8")
            record["log_prefix"] = str(log)
            if process.returncode:
                raise ValueError(f"CLI exit {process.returncode}; see {log}.stderr.txt")
            payload = json.loads(process.stdout)
            report = Path(payload["report_directory"])
            result = json.loads((report / "result.json").read_text(encoding="utf-8"))
            if BacktestRequest.model_validate(result["request"]) != req:
                raise ValueError("Executed configuration differs from the planned YAML")
            if (result["data_quality"]["data_sha256"] != data_hash
                    or result["data_quality"]["source_sha256"] != code_hash):
                raise ValueError("Data/code changed during batch; restart to re-plan")
            record.update(status="succeeded", run_id=payload["run_id"],
                          report_directory=str(report), **payload["summary"])
            counts = Counter(trade["exit_reason"] for trade in result["trades"])
            for reason in ("stop_loss", "take_profit", "liquidation"):
                record[f"{reason}_exits"] = counts[reason]
            if not report_intact(record):
                raise ValueError("Incomplete or inconsistent report bundle")
            completed += 1
        except KeyboardInterrupt:
            record.update(status="interrupted", finished_at=now())
            save_records(directory, records)
            raise
        except (OSError, ValueError, KeyError) as exc:
            record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            failed += 1
            print(f"FAILED: {record['error']}", flush=True)
        record["finished_at"] = now()
        save_records(directory, records)
    save_records(directory, records)
    print(f"Batch finished: {completed} succeeded, {skipped} resumed/skipped, {failed} failed.")
    print(f"Comparison CSV: {directory / 'summary.csv'}")
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--plan", action="store_true", help="Validate/count YAMLs; no DB or execution")
    parser.add_argument("--version", action="append", default=[])
    parser.add_argument("--symbol", action="append", choices=COINS, default=[])
    parser.add_argument("--market", choices=("spot", "perpetual"))
    parser.add_argument("--limit", type=int, help="Maximum new executions; completed jobs do not count")
    parser.add_argument("--rerun", action="store_true", help="Re-execute even successful matching jobs")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    root = args.config_root.expanduser().resolve()
    if args.generate_only:
        generate(root)
        return 0
    jobs, skipped = discover(root, args.version, args.symbol, args.market)
    print(json.dumps({"selected": len(jobs), "by_version": dict(Counter(
        req.strategy_version for _, req in jobs)), "unimplemented_skipped": len(skipped)}))
    if not jobs:
        raise ValueError("No runnable YAMLs found; check filters or run --generate-only first")
    if args.plan:
        return 0
    directory = args.state_dir.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with batch_lock(directory):
        signatures = preflight(jobs)
        return run_jobs(jobs, directory, signatures, limit=args.limit, rerun=args.rerun)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted. Run the same command to resume.", file=sys.stderr)
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"{type(exc).__name__}: batch stopped; check configuration/data and logs.",
              file=sys.stderr)
        if isinstance(exc, (ValueError, RuntimeError)):
            print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
