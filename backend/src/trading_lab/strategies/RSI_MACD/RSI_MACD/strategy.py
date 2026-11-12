"""User-authored strategy slot. No indicators or trading rules are implemented."""

from datetime import UTC, datetime

from trading_lab.config import Settings
from trading_lab.domain.enums import MarketType
from trading_lab.infrastructure.database.dataframe import  candles_frame
from trading_lab.infrastructure.database.engine import (
    build_engine,
    build_session_factory
)
from trading_lab.infrastructure.database.repositories import (
    PostgresMarketDataRepository
)

from trading_lab.strategies.RSI_MACD.Indica

engine = build_engine(Settings())
sessions = build_session_factory(engine)

try:
    with sessions() as session:
        repository = PostgresMarketDataRepository(session)

        market = repository.find_market(
            exchange="binance",
            market_type=MarketType.SPOT,
            symbol="BTC/USDT",
        )

        if market is None:
            raise ValueError("No stored market data")

        candles = list(
            repository.iter_candles(
                market,
                timeframe="1h",
                start=datetime(2021, 1, 1, tzinfo=UTC),
                end=datetime(2021, 1, 3, tzinfo=UTC)
            )
        )

        prices = candles_frame(candles)

        print(prices.head())
        print("Entire candle amount: ", len(prices))
        print(prices["close"].head())

finally:
    engine.dispose()