"""Run isolated development MACD using the existing read-only DB/engine APIs."""

# ruff: noqa: E402 -- direct-script entry point adds its parent before package imports.

import argparse
import hashlib
import json
import sys
from pathlib import Path
from uuid import uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.exc import SQLAlchemyError
from trading_lab.application.backtest_service import BacktestService
from trading_lab.config import Settings
from trading_lab.domain.enums import MarketType
from trading_lab.domain.exceptions import TradingLabError
from trading_lab.infrastructure.database.engine import build_engine, build_session_factory
from trading_lab.infrastructure.database.unit_of_work import data_unit_factory
from trading_lab.interfaces.cli import load_request

from backend_dev.backtesting.service import run_backtest as run_v2
from backend_dev.reporting.service import ReportService, parameter_label
from backend_dev.strategies.bollinger_mr.v1 import UserStrategy as BollingerV1
from backend_dev.strategies.macd.v1 import UserStrategy as MACDv1
from backend_dev.strategies.macd.v2 import UserStrategy as MACDv2
from backend_dev.strategies.macd.v3 import UserStrategy as MACDv3
from backend_dev.strategies.rsi_macd.v1 import UserStrategy as CombinedV1
from backend_dev.strategies.rsi_macd.v2 import UserStrategy as CombinedV2
from backend_dev.strategies.rsi_macd.v3 import UserStrategy as CombinedV3
from backend_dev.strategies.rsi_macd.v4 import UserStrategy as CombinedV4
from backend_dev.strategies.rsi_macd.v5 import UserStrategy as CombinedV5
from backend_dev.strategies.rsi_macd.v6 import UserStrategy as CombinedV6
from backend_dev.strategies.rsi_macd.v6 import matched_allocation_pct

DEV_DIR = Path(__file__).resolve().parent


def development_hash():
    digest = hashlib.sha256()
    paths = [DEV_DIR / "__init__.py", DEV_DIR / "run_backtest.py"]
    for directory in (
        DEV_DIR / "indicators",
        DEV_DIR / "strategies",
        DEV_DIR / "backtesting",
        DEV_DIR / "reporting",
    ):
        paths.extend(directory.rglob("*.py"))
    for path in sorted(paths):
        digest.update(path.relative_to(DEV_DIR).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--check", action="store_true", help="Validate only; no DB access")
    parser.add_argument("--exit-middle", choices=("dynamic", "fixed"), help="Bollinger v1 override")
    args = parser.parse_args(argv)
    path = args.config if args.config.is_absolute() else DEV_DIR / args.config
    request = load_request(path)
    combined = {
        "v1": CombinedV1, "v2": CombinedV2, "v3": CombinedV3,
        "v4": CombinedV4, "v5": CombinedV5, "v6": CombinedV6,
    }
    if request.strategy_id == "rsi_macd" and request.strategy_version in combined:
        strategy_class = combined[request.strategy_version]
    elif request.strategy_id == "macd" and request.strategy_version in ("v1", "v2", "v3"):
        strategy_class = {"v1": MACDv1, "v2": MACDv2, "v3": MACDv3}[request.strategy_version]
    elif request.strategy_id == "bollinger_mr" and request.strategy_version == "v1":
        strategy_class = BollingerV1
    else:
        raise ValueError(
            "Supported development strategies: macd/v1-v3, rsi_macd/v1-v6, bollinger_mr/v1"
        )
    if args.exit_middle:
        if strategy_class is not BollingerV1:
            parser.error("--exit-middle requires bollinger_mr/v1")
        request = request.model_copy(
            update={
                "strategy_parameters": {
                    **request.strategy_parameters,
                    "exit_middle": args.exit_middle,
                }
            }
        )
    strategy = strategy_class(**request.strategy_parameters)
    if strategy_class is CombinedV6:
        request = strategy.effective_request(request)
    elif strategy_class is BollingerV1 and request.market_type is MarketType.PERPETUAL:
        request = request.model_copy(update={"allocation_pct": matched_allocation_pct(request)})
    strategy.validate_request(request)
    if args.check:
        print(
            json.dumps(
                {
                    "config": str(path),
                    "parameters": strategy.parameters,
                    "required_warmup_bars": strategy.required_warmup_bars,
                    "allocation_pct": str(request.allocation_pct),
                    "report_root": str(DEV_DIR / "reports"),
                },
                default=str,
                indent=2,
            )
        )
        return 0
    engine = build_engine(Settings())  # Read backend/.env; no new environment or migration.
    try:
        sessions = build_session_factory(engine)
        # No run store: existing DB is queried, but run/trade tables are not written.
        units = data_unit_factory(sessions)
        if request.strategy_version == "v1":
            result = BacktestService(units).run(request, strategy=strategy)
        else:
            result = run_v2(request, strategy, units)
    finally:
        engine.dispose()
    result = result.model_copy(
        update={
            "data_quality": {
                **result.data_quality,
                "development_source_sha256": development_hash(),
                "development_mode": True,
            }
        }
    )
    reports = ReportService(DEV_DIR / "reports")
    if strategy_class is BollingerV1:
        destination = reports.export(result, signal_bands=strategy.signal_bands)
    else:
        destination = reports.export(result)
    if request.strategy_id == "macd" and request.strategy_version in ("v2", "v3"):
        # No DB run store refers to this path. Rename the completed bundle locally
        # to expose MACD risk settings without changing the shared report writer.
        p = strategy.parameters
        suffix = (
            f"-SL{parameter_label(request.stop_loss_pct)}-TP{parameter_label(request.take_profit_pct)}"
            f"-MACD{p['fast']}-{p['slow']}-{p['signal']}"
        )
        target = destination.with_name(destination.name + suffix)
        while target.exists():
            target = destination.with_name(destination.name + suffix + "__" + uuid4().hex[:8])
        destination = destination.rename(target)
    print(
        json.dumps(
            {
                "run_id": str(result.run_id),
                "report_directory": str(destination),
                "summary": result.summary,
            },
            default=str,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SQLAlchemyError as exc:
        print(
            f"Database error ({type(exc).__name__}); check backend DB configuration",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except (TradingLabError, ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
