"""Offline fixture demonstration. Never registered or presented as a real strategy."""

import argparse
from pathlib import Path

from tests.fixtures.fakes import MemoryData, MemoryState, memory_units
from tests.fixtures.scenarios import ScheduledStrategy, bars, market, request
from trading_lab.application.backtest_service import BacktestService
from trading_lab.application.report_service import ReportService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).resolve().parents[2] / "reports"
    )
    args = parser.parse_args()
    state = MemoryState()
    data = MemoryData(state)
    data.save_market(market())
    data.upsert_candles(market(), "1h", bars([100, 100, 110, 120]))
    result = BacktestService(memory_units(state)).run(request(), strategy=ScheduledStrategy())
    destination = ReportService(args.output).export(result)
    print(f"FIXTURE ONLY: ending equity={result.summary['ending_equity']}; report={destination}")


if __name__ == "__main__":
    main()
