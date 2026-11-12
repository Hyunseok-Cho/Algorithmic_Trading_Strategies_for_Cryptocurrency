"""Explicit, tiny live check: market metadata and at most two historical records."""

import argparse
import json
from datetime import UTC, datetime, timedelta

from trading_lab.domain.enums import MarketType
from trading_lab.infrastructure.exchanges.ccxt_provider import CCXTProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=["spot", "perpetual"], default="spot")
    args = parser.parse_args()
    market_type = MarketType(args.market)
    symbol = "BTC/USDT" if market_type is MarketType.SPOT else "BTC/USDT:USDT"
    provider = CCXTProvider(market_type, max_retries=0, timeout_ms=10000)
    start = datetime(2021, 1, 1, tzinfo=UTC)
    try:
        market = provider.get_market(symbol)
        candles = provider.fetch_candles(
            market, "1h", start=start, end=start + timedelta(hours=2), limit=2
        )
        record = {
            "market": args.market,
            "symbol": symbol,
            "candles": len(candles),
            "first_open_time": candles[0].open_time.isoformat() if candles else None,
        }
        if market_type is MarketType.PERPETUAL:
            rates = provider.fetch_funding_rates(
                market, start=start, end=start + timedelta(days=1), limit=2
            )
            record["funding_events"] = len(rates)
        print(json.dumps(record))
    except Exception as exc:
        print(
            json.dumps(
                {"market": args.market, "error_type": type(exc).__name__, "message": str(exc)}
            )
        )
        raise SystemExit(1) from None
    finally:
        provider.close()


if __name__ == "__main__":
    main()
