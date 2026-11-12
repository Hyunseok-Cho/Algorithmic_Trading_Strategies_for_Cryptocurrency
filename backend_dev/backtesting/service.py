"""Read-only protective service for MACD/combined v2-v3; no DB run/trade writes."""

from trading_lab.application.backtest_service import code_identity, fingerprint
from trading_lab.application.dto import BacktestResult
from trading_lab.backtesting.metrics import calculate_metrics
from trading_lab.domain.enums import MarketType
from trading_lab.domain.exceptions import DataCoverageError
from trading_lab.domain.timeframes import timeframe_delta

from backend_dev.backtesting.engine import run_engine

DEV_MODEL_VERSION = "macd-dev-v2-protective-sl-1"
DEV_V3_MODEL_VERSION = "macd-dev-v3-protective-tpsl-1"


def load_market_data(request, units):
    first = request.start_time - request.warmup_bars * timeframe_delta(request.timeframe)
    with units() as unit:
        market = unit.data.find_market(request.exchange, request.market_type, request.symbol)
        if market is None:
            raise DataCoverageError(
                "No stored market; data sync is required after the active batch"
            )
        candles = tuple(
            unit.data.iter_candles(
                market,
                request.timeframe,
                start=first,
                end=request.end_time,
            )
        )
        funding = (
            tuple(
                unit.data.iter_funding_rates(
                    market,
                    start=request.start_time,
                    end=request.end_time,
                )
            )
            if request.market_type is MarketType.PERPETUAL
            else ()
        )
    return market, candles, funding


def run_backtest(request, strategy, units):
    strategy.validate_request(request)
    market, candles, funding = load_market_data(request, units)
    portfolio, curve, assumptions, warnings = run_engine(request, candles, strategy, funding)
    summary, daily = calculate_metrics(request, portfolio, curve, candles)
    revision, source_hash = code_identity(strategy)
    if request.strategy_id == "rsi_macd":
        model_version = f"rsi-macd-dev-{request.strategy_version}-protective-1"
    else:
        model_version = (
            DEV_V3_MODEL_VERSION if request.strategy_version == "v3" else DEV_MODEL_VERSION
        )
    return BacktestResult(
        model_version=model_version,
        code_revision=revision,
        request=request,
        summary=summary,
        trades=tuple(portfolio.trades),
        equity_curve=curve,
        daily_statistics=daily,
        assumptions=assumptions,
        warnings=warnings,
        order_count=portfolio.order_count,
        data_quality={
            "exchange": market.exchange,
            "market": market.symbol,
            "market_type": market.market_type.value,
            "timeframe": request.timeframe,
            "strategy_version": request.strategy_version,
            "strategy_effective_parameters": strategy.parameters,
            "candle_count": len(candles),
            "funding_event_count": len(funding),
            "includes_warmup": request.warmup_bars,
            "data_sha256": fingerprint(candles, funding),
            "source_sha256": source_hash,
            "funding_schedule_source": request.funding_schedule_source,
        },
    )
