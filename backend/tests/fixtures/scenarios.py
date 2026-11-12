"""Synthetic bars and scheduled order intents; no real strategy indicators."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_lab.application.dto import BacktestRequest
from trading_lab.domain.enums import MarketType, SignalAction
from trading_lab.domain.models import Candle, Market
from trading_lab.strategies.base import OrderIntent

START = datetime(2021, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


def bars(prices, *, start=START):
    return tuple(
        Candle(
            start + index * HOUR,
            Decimal(str(price)),
            Decimal(str(price)) + 1,
            Decimal(str(price)) - 1 if Decimal(str(price)) > 1 else Decimal("0.1"),
            Decimal(str(price)),
            Decimal("1"),
        )
        for index, price in enumerate(prices)
    )


def market(perpetual=False):
    return (
        Market(
            "binance",
            MarketType.PERPETUAL,
            "BTC/USDT:USDT",
            "BTCUSDT",
            "BTC",
            "USDT",
            "USDT",
            Decimal("1"),
        )
        if perpetual
        else Market("binance", MarketType.SPOT, "BTC/USDT", "BTCUSDT", "BTC", "USDT")
    )


def request(count=4, **changes):
    values = dict(
        symbol="BTC/USDT",
        start_time=START,
        end_time=START + count * HOUR,
        strategy_id="fixture",
        initial_capital="1000",
        fee_rate_open="0",
        fee_rate_close="0",
        slippage_bps="0",
    )
    values.update(changes)
    return BacktestRequest.model_validate(values)


class ScheduledStrategy:
    def __init__(self, actions=None):
        self.actions = actions or {0: SignalAction.OPEN_LONG, 2: SignalAction.CLOSE}
        self.contexts = []

    def on_bar(self, context):
        self.contexts.append(context)
        value = self.actions.get(len(context.history) - 1)
        return OrderIntent(value) if isinstance(value, SignalAction) else value


class NoTrades:
    def on_bar(self, context):
        return None
