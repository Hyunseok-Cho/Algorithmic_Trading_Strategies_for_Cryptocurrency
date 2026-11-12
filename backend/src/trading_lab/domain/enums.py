"""Shared domain vocabulary, independent of the CLI, database and exchange SDK."""

from enum import StrEnum, unique


@unique
class MarketType(StrEnum):
    """Perpetual initially means a USDT-settled linear perpetual contract."""

    SPOT = "spot"
    PERPETUAL = "perpetual"


@unique
class PositionSide(StrEnum):
    """Direction of an existing position; a flat account has no position."""

    LONG = "long"
    SHORT = "short"


@unique
class OrderSide(StrEnum):
    """Execution side: a buy may open a long or close a short."""

    BUY = "buy"
    SELL = "sell"


@unique
class SignalAction(StrEnum):
    """Strategy intent, not a fill. Return None when no action is requested.

    CLOSE means close the current position. Reversal and execution decisions
    belong to the engine; these values contain no strategy or trading rules.
    """

    OPEN_LONG = "open_long"
    OPEN_SHORT = "open_short"
    CLOSE = "close"
    # Explicit targets may close an opposite position before entering at the same next open.
    TARGET_LONG = "target_long"
    TARGET_SHORT = "target_short"


@unique
class DirectionMode(StrEnum):
    """Allowed entry directions; spot requests must select LONG_ONLY."""

    LONG_ONLY = "long_only"
    SHORT_ONLY = "short_only"
    LONG_SHORT = "long_short"


@unique
class PositionMode(StrEnum):
    """Position layout requested by the caller.

    HEDGE allows independent long and short positions on the same market.
    Declaring it here does not imply engine support: unsupported modes must
    be rejected explicitly, never silently executed as ONE_WAY.
    """

    ONE_WAY = "one_way"
    HEDGE = "hedge"


@unique
class MarginMode(StrEnum):
    """Supported perpetual margin model; not applicable to spot accounting."""

    ISOLATED = "isolated"


@unique
class FundingMode(StrEnum):
    """STRICT rejects missing funding; ASSUME_ZERO is an explicit simplification."""

    STRICT = "strict"
    ASSUME_ZERO = "assume_zero"
