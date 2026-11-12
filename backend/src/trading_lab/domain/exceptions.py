"""Application error categories independent of CCXT, SQLAlchemy and the CLI.

Adapters translate expected SDK failures at their boundaries and preserve the
cause with `raise ... from exc`. Public messages must describe the operation
without embedding credentials, database URLs or raw authenticated responses.
Unexpected programming errors must not be blanket-converted into these types.
"""


class TradingLabError(Exception):
    """Base for expected failures the CLI can explain without a traceback."""


class MarketDataError(TradingLabError):
    """A market-data operation could not satisfy its contract."""


class ProviderError(MarketDataError):
    """An exchange request failed; not retryable unless explicitly classified."""


class TransientProviderError(ProviderError):
    """An adapter-classified temporary failure, such as timeout or rate limiting.

    The provider owns bounded retries. After exhaustion, propagate the error;
    the application must not silently add another unbounded retry loop.
    Exchange bans and permanent denials are not automatically transient.
    """


class UnsupportedMarketError(ProviderError):
    """The requested exchange, exact symbol or contract type is unsupported."""


class UnsupportedTimeframeError(ProviderError):
    """The exchange does not provide the requested OHLCV interval."""


class FundingHistoryUnavailableError(ProviderError):
    """Historical funding access is unsupported or explicitly unavailable.

    A timeout is a transient provider error, not evidence of unsupported
    history. Empty funding pages alone do not establish unavailability.
    """


class InvalidMarketDataError(MarketDataError):
    """Observed data is malformed, inconsistent or contains conflicting duplicates.

    Reject it instead of fabricating replacements, dropping it silently or
    retrying permanent validation failures as if they were network errors.
    """


class DataCoverageError(MarketDataError):
    """Stored data cannot support the requested experiment, including warmup.

    Missing candle or required funding coverage is not an observed zero.
    In strict mode the caller must reject the experiment explicitly.
    """


class RepositoryError(TradingLabError):
    """An expected persistence failure, with the original DB error chained.

    The transaction owner controls rollback and failure recording. This error
    never grants permission to reconnect and replay a transaction whose commit
    outcome may be unknown.
    """
