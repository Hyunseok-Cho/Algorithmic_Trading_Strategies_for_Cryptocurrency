"""The V6 CLI derives the same opening notional for every leverage."""

from decimal import Decimal, localcontext

import pytest
from trading_lab.backtesting.portfolio import Portfolio
from trading_lab.interfaces.cli import load_request

from backend_dev.run_backtest import DEV_DIR, main
from backend_dev.strategies.rsi_macd.v6 import UserStrategy


@pytest.mark.parametrize("leverage", range(1, 6))
def test_v6_matches_1x_opening_notional(leverage, capsys):
    path = DEV_DIR / f"config/rsi_macd/v6/btc_1h_long_short_{leverage}x.yaml"
    config = load_request(path)
    strategy = UserStrategy(**config.strategy_parameters)
    effective = strategy.effective_request(config)
    strategy.validate_request(effective)
    assert main(["--config", str(path), "--check"]) == 0
    assert str(effective.allocation_pct) in capsys.readouterr().out

    with localcontext() as context:
        context.prec = 50
        baseline = Portfolio(config.model_copy(update={"leverage": Decimal(1)}))
        account = Portfolio(effective)
        for portfolio in (baseline, account):
            portfolio.open("long", Decimal(100), config.start_time)
        assert abs(account.position.quantity - baseline.position.quantity) < Decimal("1e-12")
        assert account.position.fees == baseline.position.fees
