"""RSI v2: reuse v1 signals; the engine adds a fixed entry-price stop loss.

RSI exits/reversals remain active. TP and post-stop re-entry restrictions are
excluded so this version measures the effect of the protective stop alone.
"""

from trading_lab.strategies.RSI_MACD.RSI.strategy import UserStrategy as RSIv1


class UserStrategy(RSIv1):
    """Share RSI math/signals without copying or changing the baseline."""

    strategy_version = "v2"

    def validate_request(self, request):
        if request.strategy_id != "rsi" or request.strategy_version != self.strategy_version:
            raise ValueError("RSI v2 implementation requires an rsi/v2 request")
        if request.stop_loss_pct is None or request.take_profit_pct is not None:
            raise ValueError("RSI v2 requires stop_loss_pct and forbids take_profit_pct")
