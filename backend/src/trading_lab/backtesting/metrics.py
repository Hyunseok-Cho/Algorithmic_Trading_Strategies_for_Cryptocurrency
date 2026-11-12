"""Performance definitions use net completed trades and UTC calendar-day equity."""

import math
from datetime import timedelta
from decimal import Decimal, localcontext
from statistics import mean, median

import numpy as np
import pandas as pd

from trading_lab.backtesting.execution import execution_price


def daily_statistics(request, curve, trades):
    # Decimal account values remain objects; float is used only for statistical ratios.
    frame = pd.DataFrame(
        {
            "time": [point.time for point in curve[1:]],
            "equity": [point.equity for point in curve[1:]],
        }
    )
    frame["time"] = pd.to_datetime(frame["time"], utc=True) - pd.Timedelta(microseconds=1)
    days = frame.set_index("time")["equity"].resample("1D").last()
    previous = request.initial_capital
    rows = []
    for timestamp, ending in days.items():
        count = sum(
            min(trade.exit_time, request.end_time - timedelta(microseconds=1)).date()
            == timestamp.date()
            for trade in trades
        )
        rows.append(
            {
                "date": timestamp.date().isoformat(),
                "opening_equity": previous,
                "ending_equity": ending,
                "pnl": ending - previous,
                "return_pct": (ending / previous - 1) * 100 if previous > 0 else None,
                "completed_trades": count,
            }
        )
        previous = ending
    return tuple(rows)


def calculate_metrics(request, portfolio, curve, bars):
    with localcontext() as context:
        context.prec = 50
        return _calculate_metrics(request, portfolio, curve, bars)


def _calculate_metrics(request, portfolio, curve, bars):
    trades = portfolio.trades
    daily = daily_statistics(request, curve, trades)
    n = len(trades)
    wins = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
    losses = [trade.net_pnl for trade in trades if trade.net_pnl < 0]
    flat = n - len(wins) - len(losses)
    peak = curve[0].equity
    peak_time = curve[0].time
    drawdown = drawdown_pct = Decimal(0)
    longest_underwater = 0.0
    dd_start = dd_end = None
    for point in curve:
        if point.equity >= peak:
            peak, peak_time = point.equity, point.time
        decline = peak - point.equity
        percentage = decline / peak * 100 if peak > 0 else Decimal(0)
        drawdown = max(drawdown, decline)
        if percentage > drawdown_pct:
            drawdown_pct, dd_start, dd_end = (
                percentage,
                peak_time.isoformat(),
                point.time.isoformat(),
            )
        if decline > 0:
            longest_underwater = max(longest_underwater, (point.time - peak_time).total_seconds())
    valid = [float(row["return_pct"]) / 100 for row in daily if row["return_pct"] is not None]
    sharpe = sortino = volatility = None
    reasons = {}
    if len(valid) < 2 or len(valid) != len(daily) or not n:
        reasons["risk_ratios"] = "Need >=2 valid daily returns and at least one completed trade"
    else:
        deviation = float(np.std(valid, ddof=1))
        downside = math.sqrt(float(np.mean(np.minimum(valid, 0) ** 2)))
        volatility = deviation * math.sqrt(365) * 100
        if deviation > 0:
            sharpe = mean(valid) / deviation * math.sqrt(365)
        else:
            reasons["sharpe"] = "Daily return standard deviation is zero"
        if downside > 0:
            sortino = mean(valid) / downside * math.sqrt(365)
        else:
            reasons["sortino"] = "No downside daily returns"
    longest_win = longest_loss = consecutive_win = consecutive_loss = 0
    for trade in trades:
        consecutive_win = consecutive_win + 1 if trade.net_pnl > 0 else 0
        consecutive_loss = consecutive_loss + 1 if trade.net_pnl < 0 else 0
        longest_win, longest_loss = (
            max(longest_win, consecutive_win),
            max(longest_loss, consecutive_loss),
        )
    period_days = (
        (request.end_time - timedelta(microseconds=1)).date() - request.start_time.date()
    ).days + 1
    active_days = {
        min(trade.exit_time, request.end_time - timedelta(microseconds=1)).date()
        for trade in trades
    }
    end_equity = curve[-1].equity
    first_price = execution_price(
        bars[request.warmup_bars].open, buy=True, slippage_bps=request.slippage_bps
    )
    last_price = execution_price(bars[-1].close, buy=False, slippage_bps=request.slippage_bps)
    budget = request.initial_capital * request.allocation_pct / 100
    quantity = budget / (first_price * (1 + request.fee_rate_open))
    hold_equity = (
        request.initial_capital - budget + quantity * last_price * (1 - request.fee_rate_close)
    )
    hold_return = (hold_equity / request.initial_capital - 1) * 100
    returns = [trade.net_return_pct for trade in trades if trade.net_return_pct is not None]
    profit_factor = sum(wins) / abs(sum(losses)) if losses else None
    if not losses:
        reasons["profit_factor"] = "No losing completed trades (zero denominator)"
    if not trades:
        reasons["trade_statistics"] = "No completed round trips"
    years = (request.end_time - request.start_time).total_seconds() / (365 * 86400)
    calmar = None
    if years >= 1 and drawdown_pct > 0 and end_equity > 0:
        annual_return = (float(end_equity / request.initial_capital) ** (1 / years) - 1) * 100
        calmar = annual_return / float(drawdown_pct)
    else:
        reasons["calmar"] = "Need >=365 days, positive ending equity and nonzero drawdown"
    summary = {
        "initial_equity": request.initial_capital,
        "ending_equity": end_equity,
        "net_pnl": end_equity - request.initial_capital,
        "total_return_pct": (end_equity / request.initial_capital - 1) * 100,
        "realized_pnl": portfolio.total_gross - portfolio.total_fees + portfolio.total_funding,
        "unrealized_pnl": curve[-1].unrealized_pnl,
        "gross_pnl": portfolio.total_gross + curve[-1].unrealized_pnl,
        "uncapped_price_pnl": portfolio.total_price_pnl + curve[-1].unrealized_pnl,
        "limited_loss_adjustment": portfolio.total_adjustment,
        "total_fees": portfolio.total_fees,
        "total_funding": portfolio.total_funding,
        "settlement_rounding_residual": end_equity
        - request.initial_capital
        - (
            portfolio.total_gross
            - portfolio.total_fees
            + portfolio.total_funding
            + curve[-1].unrealized_pnl
        ),
        "completed_trades": n,
        "order_count": portfolio.order_count,
        "open_positions": int(portfolio.position is not None),
        "long_trades": sum(trade.position_side == "long" for trade in trades),
        "short_trades": sum(trade.position_side == "short" for trade in trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "breakeven_trades": flat,
        "win_rate_pct": Decimal(len(wins)) / n * 100 if n else None,
        "total_profit": sum(wins, Decimal(0)),
        "total_loss": sum(losses, Decimal(0)),
        "best_profit": max(wins) if wins else None,
        "worst_loss": min(losses) if losses else None,
        "average_profit": mean(wins) if wins else None,
        "average_loss": mean(losses) if losses else None,
        "median_trade_pnl": median([trade.net_pnl for trade in trades]) if n else None,
        "average_trade_return_pct": mean(returns) if returns else None,
        "average_winning_return_pct": mean([t.net_return_pct for t in trades if t.net_pnl > 0])
        if wins
        else None,
        "average_losing_return_pct": mean([t.net_return_pct for t in trades if t.net_pnl < 0])
        if losses
        else None,
        "average_holding_seconds": mean([trade.duration_seconds for trade in trades])
        if n
        else None,
        "calendar_days": period_days,
        "average_trades_per_calendar_day": n / period_days,
        "average_trades_per_active_day": n / len(active_days) if active_days else None,
        "longest_win_streak": longest_win,
        "longest_loss_streak": longest_loss,
        "profit_factor": profit_factor,
        "expectancy": sum((trade.net_pnl for trade in trades), Decimal(0)) / n if n else None,
        "max_drawdown": drawdown,
        "max_drawdown_pct": drawdown_pct,
        "max_drawdown_start": dd_start,
        "max_drawdown_end": dd_end,
        "longest_underwater_seconds": longest_underwater,
        "sharpe": sharpe,
        "sortino": sortino,
        "annualized_volatility_pct": volatility,
        "calmar": calmar,
        "buy_and_hold_ending_equity": hold_equity,
        "buy_and_hold_return_pct": hold_return,
        "excess_return_pct": (end_equity / request.initial_capital - 1) * 100 - hold_return,
        "buy_and_hold_definition": "Unlevered hypothetical hold using the same trade-price dataset, "
        "allocation and fees/slippage; excludes funding and liquidation",
        "na_reasons": reasons,
    }
    return summary, daily
