"""Explicit registry; test fixtures are never registered as production strategies."""

from dataclasses import dataclass
from importlib import import_module

from trading_lab.domain.exceptions import TradingLabError


class StrategyNotImplemented(TradingLabError, NotImplementedError):
    """The requested strategy slot has no user-authored trading logic yet."""


@dataclass(frozen=True)
class StrategyInfo:
    id: str
    name: str
    module: str
    implemented: bool = False


STRATEGIES = (
    StrategyInfo("rsi", "RSI", "trading_lab.strategies.RSI_MACD.RSI.strategy", implemented=True),
    StrategyInfo("macd", "MACD", "trading_lab.strategies.RSI_MACD.MACD.strategy"),
    StrategyInfo("rsi_macd", "RSI+MACD", "trading_lab.strategies.RSI_MACD.RSI_MACD.strategy"),
)


@dataclass(frozen=True)
class StrategyVersionInfo:
    version: str
    description: str
    module: str
    implemented: bool = False


RSI_VERSIONS = (
    StrategyVersionInfo(
        "v1", "Original RSI exits and reversals; no TP/SL",
        "trading_lab.strategies.RSI_MACD.RSI.strategy", implemented=True,
    ),
    StrategyVersionInfo(
        "v2", "RSI exits/reversals plus a fixed entry-price SL",
        "trading_lab.strategies.RSI_MACD.RSI.versions.v2.strategy", implemented=True,
    ),
    StrategyVersionInfo(
        "v3", "RSI exits/reversals plus fixed entry-price SL and TP",
        "trading_lab.strategies.RSI_MACD.RSI.versions.v3.strategy", implemented=True,
    ),
    StrategyVersionInfo(
        "v4", "v3 plus same-direction re-entry restriction after SL (placeholder)",
        "trading_lab.strategies.RSI_MACD.RSI.versions.v4.strategy",
    ),
)


def strategy_versions(strategy_id: str):
    if strategy_id == "rsi":
        return RSI_VERSIONS
    info = next((item for item in STRATEGIES if item.id == strategy_id), None)
    if info is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")
    return (StrategyVersionInfo("v1", info.name, info.module, info.implemented),)


def create_strategy(strategy_id: str, parameters: dict, *, version: str = "v1"):
    info = next((item for item in STRATEGIES if item.id == strategy_id), None)
    if info is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")
    selected = next((item for item in strategy_versions(strategy_id) if item.version == version), None)
    if selected is None:
        raise ValueError(f"Unknown version for {strategy_id}: {version}")
    if not selected.implemented:
        raise StrategyNotImplemented(
            f"{info.name} {version} is not implemented. Edit {selected.module} first."
        )
    return import_module(selected.module).UserStrategy(**parameters)
