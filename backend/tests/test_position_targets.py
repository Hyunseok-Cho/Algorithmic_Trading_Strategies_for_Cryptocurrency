from decimal import Decimal

import pytest

from tests.fixtures.scenarios import HOUR, START, ScheduledStrategy, bars, request
from trading_lab.backtesting.engine import run_engine
from trading_lab.domain.enums import SignalAction
from trading_lab.domain.models import FundingRate


@pytest.mark.parametrize("first", [SignalAction.TARGET_LONG, SignalAction.TARGET_SHORT])
def test_both_reversal_directions_close_then_open_and_pay_each_leg(first):
    second = (
        SignalAction.TARGET_SHORT if first is SignalAction.TARGET_LONG else SignalAction.TARGET_LONG
    )
    req = request(
        market_type="perpetual",
        symbol="BTC/USDT:USDT",
        direction_mode="long_short",
        funding_mode="assume_zero",
        fee_rate_open="0.001",
        fee_rate_close="0.002",
        slippage_bps="10",
    )
    account, curve, assumptions, _ = run_engine(
        req, bars([100] * 4), ScheduledStrategy({0: first, 1: second})
    )
    assert len(account.trades) == 2 and account.order_count == 4
    assert account.trades[0].exit_time == account.trades[1].entry_time == START + 2 * HOUR
    assert account.trades[0].exit_reason == "reversal"
    assert all(trade.fees > 0 for trade in account.trades)
    assert account.trades[0].entry_price != account.trades[0].exit_price
    assert curve[-1].equity < req.initial_capital
    assert any("both legs" in value for value in assumptions)
    assert abs(
        curve[-1].equity - req.initial_capital - account.total_gross + account.total_fees
    ) < Decimal("1e-10")


def test_same_target_is_not_pyramiding_and_does_not_pay_extra_costs():
    req = request(
        market_type="perpetual",
        symbol="BTC/USDT:USDT",
        direction_mode="long_short",
        funding_mode="assume_zero",
    )
    account, _, _, _ = run_engine(
        req,
        bars([100] * 4),
        ScheduledStrategy(
            {0: SignalAction.TARGET_LONG, 1: SignalAction.TARGET_LONG, 2: SignalAction.TARGET_LONG}
        ),
    )
    assert len(account.trades) == 1 and account.order_count == 2


def test_spot_short_target_is_rejected_instead_of_opening_a_short():
    with pytest.raises(ValueError, match="direction_mode"):
        run_engine(request(), bars([100] * 4), ScheduledStrategy({0: SignalAction.TARGET_SHORT}))


def test_funding_at_reversal_open_charges_old_position_only():
    event = FundingRate(START + 2 * HOUR, Decimal("0.01"), "fixture", Decimal(100))
    req = request(
        market_type="perpetual",
        symbol="BTC/USDT:USDT",
        direction_mode="long_short",
        expected_funding_times=[event.funding_time],
        funding_schedule_source="test audit",
    )
    account, _, _, _ = run_engine(
        req,
        bars([100] * 4),
        ScheduledStrategy({0: SignalAction.TARGET_LONG, 1: SignalAction.TARGET_SHORT}),
        [event],
    )
    assert account.trades[0].funding == -10
    assert account.trades[1].funding == 0
