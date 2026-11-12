"""V5 entries and exits with fee-adjusted sizing anchored to 1x."""

from decimal import Decimal, localcontext

from backend_dev.strategies.rsi_macd.v5 import UserStrategy as CombinedV5


def matched_allocation_pct(request):
    with localcontext() as context:
        context.prec = 50
        fee = request.fee_rate_open
        return Decimal(100) * (1 / request.leverage + fee) / (1 + fee)


class UserStrategy(CombinedV5):
    strategy_version = "v6"

    def effective_request(self, request):
        return request.model_copy(update={"allocation_pct": matched_allocation_pct(request)})

    def validate_request(self, request):
        super().validate_request(request)
        if request.allocation_pct != matched_allocation_pct(request):
            raise ValueError("Combined v6 requires the fee-adjusted 1x allocation")
