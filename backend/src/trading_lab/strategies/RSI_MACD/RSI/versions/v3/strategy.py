"""RSI v3: original RSI signals plus fixed entry-price SL and TP.

RSI exits/reversals stay active. The engine handles protective price exits.
No post-stop re-entry restriction is applied; that belongs to v4.
"""

from trading_lab.strategies.RSI_MACD.RSI.strategy import UserStrategy as RSIv1


class UserStrategy(RSIv1):
    """Reuse baseline RSI math/signals; require both protective exit levels."""

    strategy_version = "v3"

    def validate_request(self, request):
        if request.strategy_id != "rsi" or request.strategy_version != self.strategy_version:
            raise ValueError("RSI v3 implementation requires an rsi/v3 request")
        if request.stop_loss_pct is None or request.take_profit_pct is None:
            raise ValueError("RSI v3 requires stop_loss_pct and take_profit_pct")
