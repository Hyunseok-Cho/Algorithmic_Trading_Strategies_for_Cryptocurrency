"""DB-only orchestration and reproducible result construction."""

import hashlib
import inspect
import json
import subprocess
from pathlib import Path
from uuid import uuid4

from trading_lab.application.dto import BacktestResult
from trading_lab.backtesting.engine import run_engine
from trading_lab.backtesting.metrics import calculate_metrics
from trading_lab.domain.exceptions import DataCoverageError
from trading_lab.domain.timeframes import timeframe_delta
from trading_lab.strategies.registry import create_strategy


def fingerprint(candles, funding):
    digest = hashlib.sha256()
    for item in (*candles, *funding):
        digest.update(repr(item).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def code_identity(strategy):
    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode())
        digest.update(path.read_bytes())
    try:
        digest.update(inspect.getsource(type(strategy)).encode())
    except (OSError, TypeError):
        digest.update(type(strategy).__qualname__.encode())
    try:
        process = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        revision = process.stdout.strip() if process.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        revision = None
    return revision, digest.hexdigest()


class BacktestService:
    def __init__(self, unit_factory, run_store=None):
        self._unit = unit_factory
        self._runs = run_store

    def run(self, request, *, strategy=None):
        strategy = (
            strategy
            if strategy is not None
            else create_strategy(
                request.strategy_id, request.strategy_parameters, version=request.strategy_version
            )
        )
        interval = timeframe_delta(request.timeframe)
        with self._unit() as unit:
            market = unit.data.find_market(request.exchange, request.market_type, request.symbol)
            if market is None:
                raise DataCoverageError("No stored market; run explicit data sync first")
            candles = tuple(
                unit.data.iter_candles(
                    market,
                    request.timeframe,
                    start=request.start_time - request.warmup_bars * interval,
                    end=request.end_time,
                )
            )
            funding = (
                tuple(
                    unit.data.iter_funding_rates(
                        market, start=request.start_time, end=request.end_time
                    )
                )
                if market.market_type.value == "perpetual"
                else ()
            )
        run_id = uuid4()
        revision, source_hash = code_identity(strategy)
        quality = {
            "strategy_version": request.strategy_version,
            "market": market.symbol,
            "exchange": market.exchange,
            "market_type": market.market_type.value,
            "timeframe": request.timeframe,
            "candle_count": len(candles),
            "funding_event_count": len(funding),
            "data_sha256": fingerprint(candles, funding),
            "source_sha256": source_hash,
            "includes_warmup": request.warmup_bars,
            "funding_schedule_source": request.funding_schedule_source,
        }
        if hasattr(strategy, "parameters"):
            quality["strategy_effective_parameters"] = strategy.parameters
        if self._runs:
            self._runs.begin(run_id, market, request, revision, quality)
        try:
            portfolio, curve, assumptions, warnings = run_engine(
                request, candles, strategy, funding
            )
            summary, daily = calculate_metrics(request, portfolio, curve, candles)
            result = BacktestResult(
                run_id=run_id,
                code_revision=revision,
                request=request,
                summary=summary,
                trades=tuple(portfolio.trades),
                equity_curve=curve,
                daily_statistics=daily,
                data_quality=quality,
                assumptions=assumptions,
                warnings=warnings,
                order_count=portfolio.order_count,
            )
            # Check JSON serialization now, before persisting an allegedly successful run.
            json.loads(result.model_dump_json())
            if self._runs:
                self._runs.complete(result)
            return result
        except (Exception, KeyboardInterrupt) as exc:
            if self._runs:
                try:
                    self._runs.fail(run_id, f"{type(exc).__name__}: backtest failed")
                except Exception:
                    exc.add_note("Could not persist failed run status")
            raise
