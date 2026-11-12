"""Spot inventory and isolated linear-perpetual accounting; no strategy logic."""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from trading_lab.application.dto import Trade
from trading_lab.backtesting.accounting import MONEY_QUANTUM, money, price_pnl
from trading_lab.domain.enums import MarketType


@dataclass
class Position:
    side: str
    entry_time: datetime
    entry_price: Decimal
    quantity: Decimal
    original_quantity: Decimal
    original_margin: Decimal
    margin: Decimal
    fees: Decimal
    funding: Decimal = Decimal(0)
    gross_pnl: Decimal = Decimal(0)
    raw_price_pnl: Decimal = Decimal(0)
    adjustment: Decimal = Decimal(0)
    exit_notional: Decimal = Decimal(0)
    liquidated: bool = False


class Portfolio:
    def __init__(self, request):
        self.request = request
        self.cash = money(request.initial_capital)
        self.position: Position | None = None
        self.total_fees = Decimal(0)
        self.total_funding = Decimal(0)
        self.total_gross = Decimal(0)
        self.total_price_pnl = Decimal(0)
        self.total_adjustment = Decimal(0)
        self.order_count = 0
        self.trades: list[Trade] = []

    def unrealized(self, price):
        p = self.position
        return Decimal(0) if p is None else price_pnl(p.side, p.quantity, p.entry_price, price)

    def equity(self, price):
        p = self.position
        if p is None:
            return self.cash
        if self.request.market_type is MarketType.SPOT:
            return money(self.cash + p.quantity * price)
        return money(self.cash + max(Decimal(0), p.margin + self.unrealized(price)))

    def open(self, side, price, timestamp):
        if self.position is not None or self.cash <= 0:
            return
        request = self.request
        budget = money(self.cash * request.allocation_pct / 100)
        notional = (budget / (1 / request.leverage + request.fee_rate_open)).quantize(
            MONEY_QUANTUM, rounding=ROUND_DOWN
        )
        if notional <= 0:
            return
        fee = money(notional * request.fee_rate_open)
        margin = money(notional / request.leverage)
        if margin + fee > budget:
            notional = max(Decimal(0), notional - MONEY_QUANTUM * request.leverage)
            fee, margin = (
                money(notional * request.fee_rate_open),
                money(notional / request.leverage),
            )
        if notional <= 0 or margin <= 0 or margin + fee > self.cash:
            return
        quantity = notional / price
        self.cash = money(self.cash - margin - fee)
        self.position = Position(side, timestamp, price, quantity, quantity, margin, margin, fee)
        self.total_fees += fee
        self.order_count += 1

    def fund(self, rate, mark):
        p = self.position
        if p is None:
            return
        amount = money(-(1 if p.side == "long" else -1) * p.quantity * mark * rate)
        p.margin = money(p.margin + amount)
        p.funding += amount
        self.total_funding += amount

    def close(self, price, timestamp, *, fraction=Decimal(1), reason="signal", liquidated=False):
        p = self.position
        if p is None:
            return
        quantity = p.quantity if fraction == 1 else p.quantity * fraction
        margin = p.margin if fraction == 1 else money(p.margin * fraction)
        fee_rate = self.request.fee_rate_close + (
            self.request.liquidation_fee_rate if liquidated else Decimal(0)
        )
        fee = money(quantity * price * fee_rate)
        raw_gross = price_pnl(p.side, quantity, p.entry_price, price)
        adjustment = Decimal(0)
        if self.request.market_type is MarketType.SPOT:
            released = money(quantity * price) - fee
        else:
            released = money(margin + raw_gross - fee)
            if released < 0:
                adjustment, released = -released, Decimal(0)
        self.cash = money(self.cash + released)
        p.quantity -= quantity
        p.margin -= margin
        p.fees += fee
        p.gross_pnl += raw_gross + adjustment
        p.raw_price_pnl += raw_gross
        p.adjustment += adjustment
        p.exit_notional += quantity * price
        p.liquidated = p.liquidated or liquidated
        self.total_fees += fee
        self.total_gross += raw_gross + adjustment
        self.total_price_pnl += raw_gross
        self.total_adjustment += adjustment
        self.order_count += 1
        if fraction == 1:
            net = p.gross_pnl - p.fees + p.funding
            self.trades.append(
                Trade(
                    trade_number=len(self.trades) + 1,
                    position_side=p.side,
                    entry_time=p.entry_time,
                    exit_time=timestamp,
                    entry_price=p.entry_price,
                    exit_price=p.exit_notional / p.original_quantity,
                    quantity=p.original_quantity,
                    capital_committed=p.original_margin,
                    price_pnl=p.raw_price_pnl,
                    limited_loss_adjustment=p.adjustment,
                    gross_pnl=p.gross_pnl,
                    fees=p.fees,
                    funding=p.funding,
                    net_pnl=net,
                    net_return_pct=net / p.original_margin * 100 if p.original_margin else None,
                    duration_seconds=(timestamp - p.entry_time).total_seconds(),
                    exit_reason=reason,
                    liquidated=p.liquidated,
                )
            )
            self.position = None
