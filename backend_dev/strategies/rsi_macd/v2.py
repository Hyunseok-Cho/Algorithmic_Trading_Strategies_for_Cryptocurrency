"""Combined v2: original MACD-filtered RSI strategy plus SL, no TP/re-entry lock."""

from backend_dev.strategies.rsi_macd.risk_settings import validate_request
from backend_dev.strategies.rsi_macd.v1 import UserStrategy as CombinedV1


class UserStrategy(CombinedV1):
    strategy_version = "v2"

    def validate_request(self, request):
        validate_request(self, request, version="v2", tp_required=False)
