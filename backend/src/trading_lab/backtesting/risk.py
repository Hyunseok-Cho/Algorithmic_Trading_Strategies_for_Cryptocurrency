"""Conservative OHLC risk triggers, not Binance's historical mark-price liquidation."""

from decimal import Decimal

from trading_lab.domain.enums import MarketType


def risk_exit(portfolio, candle):
    p, request = portfolio.position, portfolio.request
    if p is None:
        return None
    long = p.side == "long"
    if request.market_type is MarketType.PERPETUAL:
        buffer = request.maintenance_margin_rate + request.liquidation_fee_rate
        threshold = (
            (p.quantity * p.entry_price - p.margin) / (p.quantity * (1 - buffer))
            if long
            else (p.quantity * p.entry_price + p.margin) / (p.quantity * (1 + buffer))
        )
        touched = candle.low <= threshold if long else candle.high >= threshold
        if touched:
            price = min(candle.open, threshold) if long else max(candle.open, threshold)
            return max(price, Decimal("0.000000000001")), "liquidation", True
    if request.stop_loss_pct is not None:
        stop = p.entry_price * (1 + (-1 if long else 1) * request.stop_loss_pct / 100)
        if candle.low <= stop if long else candle.high >= stop:
            return (min(candle.open, stop) if long else max(candle.open, stop)), "stop_loss", False
    if request.take_profit_pct is not None:
        target = p.entry_price * (1 + (1 if long else -1) * request.take_profit_pct / 100)
        if candle.high >= target if long else candle.low <= target:
            return target, "take_profit", False
    return None


def protective_stop_exit(portfolio, candle, *, opening_only=False, stop_loss_pct=None):
    """v2 SL policy: open gaps first, then the nearest adverse barrier.

    Stop levels use the actual entry fill, not margin ROI. Beyond-liquidation
    opening gaps cannot be rescued by assuming a fill at the skipped stop.
    Intrabar timestamps remain approximated by the engine at candle end.
    """
    p, request = portfolio.position, portfolio.request
    if p is None:
        return None
    long = p.side == "long"
    sl = request.stop_loss_pct if stop_loss_pct is None else stop_loss_pct
    stop = p.entry_price * (1 + (-1 if long else 1) * sl / 100)
    liquidation = None
    if request.market_type is MarketType.PERPETUAL:
        buffer = request.maintenance_margin_rate + request.liquidation_fee_rate
        liquidation = (
            (p.quantity * p.entry_price - p.margin) / (p.quantity * (1 - buffer))
            if long else
            (p.quantity * p.entry_price + p.margin) / (p.quantity * (1 + buffer))
        )

    def crossed(price, level):
        return price <= level if long else price >= level

    if liquidation is not None and crossed(candle.open, liquidation):
        return candle.open, "liquidation", True
    if crossed(candle.open, stop):
        return candle.open, "stop_loss", False
    if opening_only:
        return None
    adverse = candle.low if long else candle.high
    barriers = []
    if crossed(adverse, stop):
        barriers.append((stop, "stop_loss", False))
    if liquidation is not None and crossed(adverse, liquidation):
        barriers.append((max(liquidation, Decimal("0.000000000001")), "liquidation", True))
    if not barriers:
        return None
    # From a solvent open, a continuous adverse move hits the closest level first.
    # Equal barriers conservatively count as liquidation.
    return sorted(barriers, key=lambda item: (
        -item[0] if long else item[0], not item[2]
    ))[0]


def protective_target_exit(
    portfolio, candle, *, opening_only=False, stop_loss_pct=None, take_profit_pct=None
):
    """v3 adds TP to v2 barriers; ambiguous intrabar adverse exits win.

    Known opening gaps are processed before any unknown intrabar ordering.
    TP is a modeled market-trigger exit, including open-price fills on gaps.
    """
    opening_risk = protective_stop_exit(
        portfolio, candle, opening_only=True, stop_loss_pct=stop_loss_pct
    )
    if opening_risk is not None or portfolio.position is None:
        return opening_risk
    p, request = portfolio.position, portfolio.request
    long = p.side == "long"
    tp = request.take_profit_pct if take_profit_pct is None else take_profit_pct
    target = p.entry_price * (1 + (1 if long else -1) * tp / 100)
    if candle.open >= target if long else candle.open <= target:
        return candle.open, "take_profit", False
    if opening_only:
        return None
    adverse_risk = protective_stop_exit(portfolio, candle, stop_loss_pct=stop_loss_pct)
    if adverse_risk is not None:
        return adverse_risk
    if candle.high >= target if long else candle.low <= target:
        return target, "take_profit", False
    return None
