"""Command-line adapter; application services remain HTTP-independent."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from itertools import islice
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
import yaml
from sqlalchemy.exc import SQLAlchemyError

from trading_lab.application.backtest_service import BacktestService
from trading_lab.application.dto import BacktestRequest
from trading_lab.application.market_data_service import MarketDataService
from trading_lab.application.report_service import ReportService
from trading_lab.config import Settings
from trading_lab.domain.enums import MarketType
from trading_lab.domain.exceptions import TradingLabError
from trading_lab.domain.timeframes import CandleRange, floor_to_bar
from trading_lab.infrastructure.database.dataframe import candles_frame
from trading_lab.infrastructure.database.engine import build_engine, build_session_factory
from trading_lab.infrastructure.database.run_repository import PostgresRunStore
from trading_lab.infrastructure.database.unit_of_work import data_unit_factory
from trading_lab.infrastructure.exchanges.ccxt_provider import CCXTProvider
from trading_lab.strategies.registry import STRATEGIES, create_strategy, strategy_versions

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
data_app = typer.Typer(no_args_is_help=True)
strategy_app = typer.Typer(no_args_is_help=True)
backtest_app = typer.Typer(no_args_is_help=True)
report_app = typer.Typer(no_args_is_help=True)
app.add_typer(data_app, name="data")
app.add_typer(strategy_app, name="strategy")
app.add_typer(backtest_app, name="backtest")
app.add_typer(report_app, name="report")


def handled(function):
    @wraps(function)
    def invoke(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except SQLAlchemyError as exc:
            typer.echo(
                f"Database error ({type(exc).__name__}); check .env and migrations", err=True
            )
            raise typer.Exit(1) from None
        except (TradingLabError, ValueError, OSError, yaml.YAMLError) as exc:
            typer.echo(f"{type(exc).__name__}: {exc}", err=True)
            raise typer.Exit(1) from None

    return invoke


def output(value):
    typer.echo(json.dumps(value, default=str, ensure_ascii=False, indent=2, allow_nan=False))


def utc_input(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        if len(value) != 10:
            raise ValueError("Use an ISO timestamp with timezone, or YYYY-MM-DD interpreted as UTC")
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@contextmanager
def runtime():
    settings = Settings()
    engine = build_engine(settings)
    try:
        sessions = build_session_factory(engine)
        yield settings, data_unit_factory(sessions), PostgresRunStore(sessions)
    finally:
        engine.dispose()


def provider(settings, market):
    return CCXTProvider(
        market,
        max_retries=settings.fetch_max_retries,
        backoff_seconds=settings.fetch_backoff_seconds,
        timeout_ms=settings.fetch_timeout_ms,
    )


def candle_range(settings, timeframe, start, end):
    return CandleRange(
        utc_input(start) if start else settings.data_start,
        utc_input(end) if end else floor_to_bar(datetime.now(UTC), timeframe),
        timeframe,
    )


@data_app.command("sync")
@handled
def data_sync(
    exchange: str = "binance",
    market: MarketType = MarketType.SPOT,
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    start: str | None = typer.Option(None, "--from"),
    end: str | None = typer.Option(None, "--to"),
    limit: int = typer.Option(500, min=1, max=1000),
    refresh: bool = typer.Option(False, help="Recheck the full requested interval, not only gaps"),
):
    if exchange != "binance":
        raise ValueError("This provider currently supports binance only")
    with runtime() as (settings, units, _):
        requested = candle_range(settings, timeframe, start, end)
        client = provider(settings, market)
        try:
            result = MarketDataService(units).sync_candles(
                client, symbol, requested, limit=limit, refresh=refresh
            )
            output(result.model_dump(mode="json"))
            if result.status == "partial":
                raise typer.Exit(2)
        finally:
            client.close()


@data_app.command("status")
@handled
def data_status(
    exchange: str = "binance",
    market: MarketType = MarketType.SPOT,
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    start: str | None = typer.Option(None, "--from"),
    end: str | None = typer.Option(None, "--to"),
):
    with runtime() as (settings, units, _):
        result = MarketDataService(units).status(
            exchange, market, symbol, candle_range(settings, timeframe, start, end)
        )
        output(result)


@data_app.command("funding-sync")
@handled
def funding_sync(
    symbol: str = "BTC/USDT:USDT",
    start: str | None = typer.Option(None, "--from"),
    end: str | None = typer.Option(None, "--to"),
    limit: int = typer.Option(500, min=1, max=1000),
    refresh: bool = False,
):
    with runtime() as (settings, units, _):
        client = provider(settings, MarketType.PERPETUAL)
        try:
            result = MarketDataService(units).sync_funding(
                client,
                symbol,
                utc_input(start) if start else settings.data_start,
                utc_input(end) if end else datetime.now(UTC),
                limit=limit,
                refresh=refresh,
            )
            output(result.model_dump(mode="json"))
        finally:
            client.close()


@data_app.command("preview")
@handled
def data_preview(
    symbol: str = "BTC/USDT",
    market: MarketType = MarketType.SPOT,
    timeframe: str = "1h",
    start: str | None = typer.Option(None, "--from"),
    end: str | None = typer.Option(None, "--to"),
    rows: int = typer.Option(10, min=1, max=10000),
):
    with runtime() as (settings, units, _):
        requested = candle_range(settings, timeframe, start, end)
        with units() as unit:
            saved = unit.data.find_market("binance", market, symbol)
            if saved is None:
                raise ValueError("Market not stored; run data sync first")
            iterator = unit.data.iter_candles(
                saved, timeframe, start=requested.start, end=requested.end
            )
            try:
                frame = candles_frame(islice(iterator, rows))
            finally:
                iterator.close()
        typer.echo(frame.to_string())


@strategy_app.command("list")
def strategy_list():
    output(
        [
            {
                "id": item.id, "name": item.name, "implemented": item.implemented,
                "versions": [
                    {"version": version.version, "description": version.description,
                     "implemented": version.implemented}
                    for version in strategy_versions(item.id)
                ],
            }
            for item in STRATEGIES
        ]
    )


class DecimalLoader(yaml.SafeLoader):
    pass


def yaml_decimal(loader, node):
    text = loader.construct_scalar(node).replace("_", "")
    aliases = {".nan": "NaN", ".inf": "Infinity", "+.inf": "Infinity", "-.inf": "-Infinity"}
    try:
        return Decimal(aliases.get(text.lower(), text))
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal value in YAML config") from exc


DecimalLoader.add_constructor("tag:yaml.org,2002:float", yaml_decimal)


def load_request(path: Path, strategy: str | None = None):
    content = path.read_text(encoding="utf-8")
    values = (
        json.loads(content, parse_float=Decimal)
        if path.suffix.lower() == ".json"
        else yaml.load(content, Loader=DecimalLoader)
    )
    if not isinstance(values, dict):
        raise ValueError("Config must contain an object/mapping")
    if strategy:
        values["strategy_id"] = strategy
    return BacktestRequest.model_validate(values)


@backtest_app.command("run")
@handled
def backtest_run(
    config: Annotated[Path, typer.Option(exists=True, dir_okay=False)], strategy: str | None = None
):
    request = load_request(config, strategy)
    implementation = create_strategy(
        request.strategy_id, request.strategy_parameters, version=request.strategy_version
    )
    with runtime() as (settings, units, runs):
        result = BacktestService(units, runs).run(request, strategy=implementation)
        path = ReportService(settings.reports_dir, runs).export(result)
        output({"run_id": result.run_id, "report_directory": path, "summary": result.summary})


@report_app.command("export")
@handled
def report_export(run_id: Annotated[UUID, typer.Option()], output_dir: Path | None = None):
    with runtime() as (settings, _, runs):
        result = runs.get(run_id)
        path = ReportService(output_dir or settings.reports_dir, runs).export(result)
        output({"run_id": result.run_id, "report_directory": path})


if __name__ == "__main__":
    app()
