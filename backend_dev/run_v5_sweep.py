"""Run the BTC perpetual V5 comparison grid and stream metrics into a CSV."""

import argparse
import csv
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from itertools import product
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trading_lab.application.backtest_service import fingerprint
from trading_lab.application.dto import BacktestRequest
from trading_lab.backtesting.metrics import calculate_metrics
from trading_lab.config import Settings
from trading_lab.domain.enums import DirectionMode
from trading_lab.infrastructure.database.engine import build_engine, build_session_factory
from trading_lab.infrastructure.database.unit_of_work import data_unit_factory
from trading_lab.interfaces.cli import load_request

from backend_dev.backtesting.engine import run_engine
from backend_dev.backtesting.service import load_market_data
from backend_dev.run_backtest import development_hash
from backend_dev.strategies.rsi_macd.v5 import LOCK_SIDES, UserStrategy

_market_data = ()
METRICS = (
    "total_return_pct", "net_pnl", "gross_pnl", "total_fees", "total_funding",
    "max_drawdown_pct", "completed_trades", "win_rate_pct", "profit_factor",
    "expectancy", "sharpe",
)
FIELDS = (
    "leverage", "stop_loss_pct", "take_profit_pct", "reentry_lock", *METRICS,
    "stop_loss_exits", "take_profit_exits", "liquidation_exits",
    "long_net_pnl", "short_net_pnl", "long_trades", "short_trades",
    "start_time", "end_time", "candle_count", "funding_event_count",
    "data_sha256", "development_source_sha256",
)


def grid():
    return product(range(1, 6), range(2, 11), (None, *range(4, 21, 2)), LOCK_SIDES)


def init_worker(base, candles, funding, hashes):
    global _market_data
    _market_data = base, candles, funding, hashes


def run_case(case):
    base, candles, funding, hashes = _market_data
    leverage, sl, tp, lock = case
    parameters = {**base.strategy_parameters, "reentry_lock": lock}
    request = BacktestRequest.model_validate({
        **base.model_dump(), "leverage": leverage, "stop_loss_pct": sl,
        "take_profit_pct": tp, "strategy_parameters": parameters,
    })
    account, curve, _, _ = run_engine(request, candles, UserStrategy(**parameters), funding)
    summary, _ = calculate_metrics(request, account, curve, candles)
    exits = Counter(trade.exit_reason for trade in account.trades)
    return {
        "leverage": leverage, "stop_loss_pct": sl, "take_profit_pct": tp,
        "reentry_lock": lock, **{key: summary[key] for key in METRICS},
        "stop_loss_exits": exits["stop_loss"], "take_profit_exits": exits["take_profit"],
        "liquidation_exits": exits["liquidation"],
        "long_net_pnl": sum(t.net_pnl for t in account.trades if t.position_side == "long"),
        "short_net_pnl": sum(t.net_pnl for t in account.trades if t.position_side == "short"),
        "long_trades": summary["long_trades"], "short_trades": summary["short_trades"],
        "start_time": request.start_time.isoformat(), "end_time": request.end_time.isoformat(),
        "candle_count": len(candles), "funding_event_count": len(funding), **hashes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    base = load_request(args.config)
    UserStrategy(**base.strategy_parameters).validate_request(base)
    if base.direction_mode is not DirectionMode.LONG_SHORT:
        parser.error("the directional-lock sweep requires long_short")
    engine = build_engine(Settings())
    try:
        _, candles, funding = load_market_data(
            base, data_unit_factory(build_session_factory(engine))
        )
    finally:
        engine.dispose()
    hashes = {
        "data_sha256": fingerprint(candles, funding),
        "development_source_sha256": development_hash(),
    }
    cases = list(grid())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        with ProcessPoolExecutor(
            max_workers=args.workers, initializer=init_worker,
            initargs=(base, candles, funding, hashes),
        ) as pool:
            for count, row in enumerate(pool.map(run_case, cases, chunksize=4), 1):
                writer.writerow(row)
                if count % 50 == 0 or count == len(cases):
                    output.flush()
                    print(f"{count}/{len(cases)} completed", flush=True)


if __name__ == "__main__":
    main()
