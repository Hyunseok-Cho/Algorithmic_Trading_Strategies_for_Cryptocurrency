"""User-authored strategy slot. No indicators or trading rules are implemented."""

from trading_lab.strategies.registry import StrategyNotImplemented


class UserStrategy:
    def __init__(self, **parameters):
        raise StrategyNotImplemented(
            "Implement this strategy and its tests before enabling the registry entry"
        )

    def on_bar(self, context):
        raise StrategyNotImplemented("Strategy logic is reserved for the user")
