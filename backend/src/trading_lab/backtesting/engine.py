"""Deterministic next-open execution over stored candles; never accesses a network."""

from decimal import Decimal, localcontext

from trading_lab.application.dto import EquityPoint
from trading_lab.backtesting.execution import execution_price
from trading_lab.backtesting.portfolio import Portfolio
from trading_lab.backtesting.risk import protective_stop_exit, protective_target_exit, risk_exit
from trading_lab.backtesting.validation import validate_inputs
from trading_lab.domain.enums import DirectionMode, FundingMode, MarketType, SignalAction
from trading_lab.domain.timeframes import timeframe_delta
from trading_lab.strategies.base import History, OrderIntent, PositionView, StrategyContext

ASSUMPTIONS = (
    "Signals inspect closed bars and execute at the next bar open; no same-close fills.",
    "No pyramiding. OPEN intents while holding are ignored; explicit TARGET intents reverse opposite positions.",
    "Reversals close the old position then open the target at the same NEXT bar open; both legs pay costs.",
    "OHLC risk priority: liquidation, stop loss, take profit; unknown tick order is approximated.",
    "Intrabar risk exits are timestamped at bar end; gap fills use the adverse open.",
    "At equal bar-open funding timestamps, carried positions pay before queued exits/entries.",
    "Intrabar funding is applied before OHLC risk checks; intra-bar timing is approximated.",
    "Perpetual liquidation uses trade OHLC and flat maintenance rates, not historical Binance tiers/mark candles.",
    "Isolated losses are capped at remaining collateral; capped gross PnL and adjustment are reported separately.",
    "Account settlement rounds half-even to 12 decimal places; quantity and prices retain Decimal precision.",
    "Fractional quantities are modeled; exchange tick/lot/min-notional constraints are not modeled.",
    "Stop/target and final forced exits incur adverse slippage and configured fees.",
)


def run_engine(request, candles, strategy, funding=()):
    if hasattr(strategy, "validate_request"):
        strategy.validate_request(request)
    candles, funding = tuple(candles), tuple(funding)
    validate_inputs(request, candles, funding)
    required = getattr(strategy, "required_warmup_bars", 0)
    if request.warmup_bars < required:
        raise ValueError(
            f"Strategy requires warmup_bars >= {required} for its first analysis-bar signal"
        )
    with localcontext() as context:
        context.prec = 50
        return _run(request, candles, strategy, funding)


def _run(request, candles, strategy, funding):
    interval = timeframe_delta(request.timeframe)
    portfolio = Portfolio(request)
    curve = [
        EquityPoint(
            time=request.start_time,
            equity=portfolio.cash,
            cash=portfolio.cash,
            margin=Decimal(0),
            unrealized_pnl=Decimal(0),
        )
    ]
    pending = None
    funding_index = 0
    warnings = []
    protective_sl = request.strategy_id == "rsi" and request.strategy_version in ("v2", "v3")
    protective_exit = (
        protective_target_exit if request.strategy_version == "v3" else protective_stop_exit
    )
    if (
        request.market_type is MarketType.PERPETUAL
        and request.funding_mode is FundingMode.ASSUME_ZERO
    ):
        warnings.append(
            "assume_zero: missing funding events are treated as zero; missing mark prices "
            "use the last completed trade close (first bar: open)."
        )
    if request.market_type is MarketType.PERPETUAL and request.funding_mode is FundingMode.STRICT:
        warnings.append(
            "Funding completeness relies on the user-audited schedule, not inference from OHLCV."
        )

    def apply_funding(event, fallback):
        if portfolio.position is not None:
            portfolio.fund(
                event.rate, event.mark_price if event.mark_price is not None else fallback
            )

    def close_risk(risk, timestamp):
        price, reason, liquidated = risk
        price = execution_price(
            price, buy=portfolio.position.side == "short", slippage_bps=request.slippage_bps
        )
        portfolio.close(price, timestamp, reason=reason, liquidated=liquidated)

    for index, bar in enumerate(candles):
        trading = bar.open_time >= request.start_time
        if trading:
            while (
                funding_index < len(funding)
                and funding[funding_index].funding_time <= bar.open_time
            ):
                apply_funding(
                    funding[funding_index], candles[index - 1].close if index else bar.open
                )
                funding_index += 1
            if protective_sl:
                opening_risk = protective_exit(portfolio, bar, opening_only=True)
                if opening_risk is not None:
                    close_risk(opening_risk, bar.open_time)
            if pending is not None:
                action = pending.action
                if action is SignalAction.CLOSE:
                    if portfolio.position is not None:
                        price = execution_price(
                            bar.open,
                            buy=portfolio.position.side == "short",
                            slippage_bps=request.slippage_bps,
                        )
                        portfolio.close(price, bar.open_time, fraction=pending.fraction)
                else:
                    side = (
                        "long"
                        if action in (SignalAction.OPEN_LONG, SignalAction.TARGET_LONG)
                        else "short"
                    )
                    if (side == "short" and request.direction_mode is DirectionMode.LONG_ONLY) or (
                        side == "long" and request.direction_mode is DirectionMode.SHORT_ONLY
                    ):
                        raise ValueError("Strategy intent violates direction_mode")
                    if (
                        action in (SignalAction.TARGET_LONG, SignalAction.TARGET_SHORT)
                        and portfolio.position is not None
                        and portfolio.position.side != side
                    ):
                        exit_price = execution_price(
                            bar.open,
                            buy=portfolio.position.side == "short",
                            slippage_bps=request.slippage_bps,
                        )
                        portfolio.close(exit_price, bar.open_time, reason="reversal")
                    price = execution_price(
                        bar.open, buy=side == "long", slippage_bps=request.slippage_bps
                    )
                    portfolio.open(side, price, bar.open_time)
                pending = None
            while (
                funding_index < len(funding)
                and funding[funding_index].funding_time < bar.open_time + interval
            ):
                fallback = candles[index - 1].close if index else bar.open
                apply_funding(funding[funding_index], fallback)
                funding_index += 1
            risk = protective_exit(portfolio, bar) if protective_sl else risk_exit(portfolio, bar)
            if risk is not None:
                close_risk(risk, bar.open_time + interval)
            if (
                index == len(candles) - 1
                and request.close_open_position_at_end
                and portfolio.position
            ):
                price = execution_price(
                    bar.close,
                    buy=portfolio.position.side == "short",
                    slippage_bps=request.slippage_bps,
                )
                portfolio.close(price, request.end_time, reason="end_of_test")
            p = portfolio.position
            curve.append(
                EquityPoint(
                    time=bar.open_time + interval,
                    equity=portfolio.equity(bar.close),
                    cash=portfolio.cash,
                    margin=p.margin if p else Decimal(0),
                    unrealized_pnl=portfolio.unrealized(bar.close),
                )
            )
        p = portfolio.position
        view = PositionView(p.side, p.quantity, p.entry_price) if p else None
        intent = strategy.on_bar(
            StrategyContext(
                time=bar.open_time + interval,
                history=History(candles, index + 1),
                equity=portfolio.equity(bar.close),
                cash=portfolio.cash,
                position=view,
                trading_enabled=trading,
                direction_mode=request.direction_mode,
            )
        )
        if intent is not None and not isinstance(intent, OrderIntent):
            raise TypeError("Strategy must return OrderIntent or None")
        if trading and index < len(candles) - 1:
            pending = intent
    if portfolio.total_adjustment:
        warnings.append("Isolated loss cap applied: inspect limited_loss_adjustment in Trades.")
    assumptions = ASSUMPTIONS
    if protective_sl:
        assumptions = tuple(
            item for item in assumptions if not item.startswith("OHLC risk priority:")
        ) + (
            f"RSI {request.strategy_version}: fixed entry-fill-price SL; RSI exits/reversals stay enabled; no re-entry lock.",
            "Protective opening gaps: liquidation before stop, processed before queued signal orders.",
            "Protective intrabar: nearest adverse SL/liquidation barrier first under a continuous-price assumption; ties liquidate.",
            "OHLC does not reveal intrabar jumps; stops are not guaranteed at their trigger prices.",
        )
        if request.strategy_version == "v3":
            assumptions += (
                "RSI v3 adds fixed entry-fill-price TP; modeled market-trigger exits pay fees and adverse slippage.",
                "v3 favorable TP opening gaps fill at open before queued signals; intrabar adverse exits win if TP is also touched.",
            )
    return portfolio, tuple(curve), assumptions, tuple(warnings)
