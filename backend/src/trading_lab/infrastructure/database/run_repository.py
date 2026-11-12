"""Run/result persistence; every public operation owns a short transaction."""

from datetime import UTC, datetime

from sqlalchemy import insert, select, update

from trading_lab import MODEL_VERSION
from trading_lab.application.dto import BacktestResult
from trading_lab.domain.exceptions import DataCoverageError, RepositoryError
from trading_lab.infrastructure.database.engine import transaction
from trading_lab.infrastructure.database.models import BacktestRunRow, BacktestTradeRow, MarketRow


class PostgresRunStore:
    def __init__(self, session_factory):
        self._sessions = session_factory

    def begin(self, run_id, market, request, revision, quality):
        with transaction(self._sessions) as session:
            market_id = session.execute(
                select(MarketRow.id).where(
                    MarketRow.exchange == market.exchange,
                    MarketRow.market_type == market.market_type,
                    MarketRow.symbol_unified == market.symbol,
                )
            ).scalar_one()
            session.execute(
                insert(BacktestRunRow.__table__).values(
                    id=run_id,
                    market_id=market_id,
                    strategy_id=request.strategy_id,
                    timeframe=request.timeframe,
                    start_time=request.start_time,
                    end_time=request.end_time,
                    parameters=request.model_dump(mode="json"),
                    data_provenance=quality,
                    model_version=MODEL_VERSION,
                    code_revision=revision,
                    status="running",
                )
            )

    def complete(self, result):
        payload = result.model_dump(mode="json")
        with transaction(self._sessions) as session:
            updated = session.execute(
                update(BacktestRunRow.__table__)
                .where(BacktestRunRow.id == result.run_id, BacktestRunRow.status == "running")
                .values(
                    status="completed",
                    summary=payload["summary"],
                    result_payload=payload,
                    warnings=payload["warnings"],
                    assumptions=payload["assumptions"],
                    finished_at=datetime.now(UTC),
                )
                .returning(BacktestRunRow.id)
            ).scalar_one_or_none()
            if updated is None:
                raise RepositoryError("Run is missing or is no longer running")
            names = (
                "trade_number",
                "position_side",
                "entry_time",
                "exit_time",
                "entry_price",
                "exit_price",
                "quantity",
                "gross_pnl",
                "fees",
                "funding",
                "net_pnl",
                "net_return_pct",
                "exit_reason",
                "liquidated",
            )
            for offset in range(0, len(result.trades), 500):
                session.execute(
                    insert(BacktestTradeRow.__table__),
                    [
                        {"run_id": result.run_id, **{name: getattr(trade, name) for name in names}}
                        for trade in result.trades[offset : offset + 500]
                    ],
                )

    def fail(self, run_id, error):
        with transaction(self._sessions) as session:
            session.execute(
                update(BacktestRunRow.__table__)
                .where(BacktestRunRow.id == run_id, BacktestRunRow.status == "running")
                .values(status="failed", error=error, finished_at=datetime.now(UTC))
            )

    def get(self, run_id):
        with transaction(self._sessions) as session:
            payload = session.execute(
                select(BacktestRunRow.result_payload).where(
                    BacktestRunRow.id == run_id, BacktestRunRow.status == "completed"
                )
            ).scalar_one_or_none()
        if payload is None:
            raise DataCoverageError("Completed run result not found")
        return BacktestResult.model_validate(payload)

    def report_status(self, run_id, *, path=None, error=None):
        with transaction(self._sessions) as session:
            session.execute(
                update(BacktestRunRow.__table__)
                .where(BacktestRunRow.id == run_id)
                .values(
                    report_status="failed" if error else "completed",
                    report_path=str(path) if path else None,
                    report_error=error,
                )
            )
