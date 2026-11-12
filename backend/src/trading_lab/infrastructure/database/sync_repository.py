"""Sync-job lifecycle and latest candle coverage in caller-owned transactions."""

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from trading_lab.domain.exceptions import DataCoverageError, InvalidMarketDataError, RepositoryError
from trading_lab.domain.models import Market
from trading_lab.domain.sync import CandleCoverage, SyncDataset, SyncJob, SyncStatus
from trading_lab.domain.timeframes import CandleRange, timeframe_delta
from trading_lab.infrastructure.database.models import DataCoverageRow, MarketRow, SyncJobRow

_TRANSITIONS = {
    SyncStatus.PENDING: {SyncStatus.RUNNING, SyncStatus.FAILED},
    SyncStatus.RUNNING: {
        SyncStatus.RUNNING,
        SyncStatus.SUCCEEDED,
        SyncStatus.PARTIAL,
        SyncStatus.FAILED,
    },
}


@contextmanager
def _database_errors() -> Iterator[None]:
    try:
        yield
    except DBAPIError as exc:
        raise RepositoryError("Sync-state database operation failed") from exc


def _details(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("Sync details must be a mapping with string keys")
    try:
        # Validate JSON compatibility, reject NaN and detach mutable caller data.
        return json.loads(json.dumps(dict(value), allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("Sync details must contain finite JSON-compatible values") from exc


def _job_values(job: SyncJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "dataset": job.dataset.value,
        "timeframe": job.timeframe,
        "requested_start": job.requested_start,
        "requested_end": job.requested_end,
        "started_at": job.started_at,
        "status": job.status.value,
        "last_committed_time": job.last_committed_time,
        "inserted_count": job.inserted_count,
        "updated_count": job.updated_count,
        "error": job.error,
        "finished_at": job.finished_at,
    }


class PostgresSyncRepository:
    """Persist job snapshots and coverage without owning commit or rollback.

    Data pages and job updates must use the same session and transaction.
    A failed transaction's error is recorded using a separate transaction.
    Updating a stale job raises instead of silently overwriting newer progress.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def _market_id(self, market: Market) -> int:
        statement = select(MarketRow.id).where(
            MarketRow.exchange == market.exchange,
            MarketRow.market_type == market.market_type,
            MarketRow.symbol_unified == market.symbol,
        )
        with _database_errors():
            market_id = self._session.execute(statement).scalar_one_or_none()
        if market_id is None:
            raise DataCoverageError("Register the local market before recording sync state")
        return market_id

    def create_job(self, job: SyncJob, *, details: Mapping[str, Any] | None = None) -> None:
        if job.status is not SyncStatus.PENDING:
            raise ValueError("New sync jobs must begin in pending state")
        payload = _job_values(job)
        payload["details"] = _details({} if details is None else details)
        payload["market_id"] = self._market_id(job.market)
        with _database_errors():
            self._session.execute(insert(SyncJobRow.__table__).values(payload)).close()

    def update_job(
        self, job: SyncJob, *, previous: SyncJob, details: Mapping[str, Any] | None = None
    ) -> None:
        """Compare-and-swap the prior snapshot, including its nullable cursor.

        previous is the last successfully persisted snapshot, not an assumed
        status. No automatic replay occurs when another writer wins the update.
        Omitted details are preserved; provided details replace the JSON object.
        """
        immutable = (
            "id",
            "market",
            "dataset",
            "timeframe",
            "requested_start",
            "requested_end",
            "started_at",
        )
        if any(getattr(job, name) != getattr(previous, name) for name in immutable):
            raise ValueError("Sync identity and requested scope cannot change")
        if job.status not in _TRANSITIONS.get(previous.status, set()):
            raise ValueError("Invalid sync-state transition; terminal jobs cannot be rewritten")
        if (
            job.inserted_count < previous.inserted_count
            or job.updated_count < previous.updated_count
        ):
            raise ValueError("Committed write counts cannot decrease")
        if previous.last_committed_time is not None:
            if (
                job.last_committed_time is None
                or job.last_committed_time < previous.last_committed_time
            ):
                raise ValueError("Highest confirmed timestamp cannot move backwards")
        payload = _job_values(job)
        if details is not None:
            payload["details"] = _details(details)
        table = SyncJobRow.__table__
        expected = {**_job_values(previous), "market_id": self._market_id(previous.market)}
        statement = (
            update(table)
            .where(*(table.c[name].is_not_distinct_from(value) for name, value in expected.items()))
            .values(payload)
            .returning(table.c.id)
        )
        with _database_errors():
            updated_id = self._session.execute(statement).scalar_one_or_none()
        if updated_id is None:
            raise RepositoryError("Sync job is missing or has changed; reload its committed state")

    @staticmethod
    def _job_query():
        return select(
            SyncJobRow.__table__,
            MarketRow.exchange,
            MarketRow.market_type,
            MarketRow.symbol_unified,
            MarketRow.symbol_native,
            MarketRow.base_asset,
            MarketRow.quote_asset,
            MarketRow.settle_asset,
            MarketRow.contract_size,
        ).join(MarketRow, SyncJobRow.market_id == MarketRow.id)

    @staticmethod
    def _decode_job(row: Mapping[str, Any]) -> SyncJob:
        try:
            market = Market(
                row["exchange"],
                row["market_type"],
                row["symbol_unified"],
                row["symbol_native"],
                row["base_asset"],
                row["quote_asset"],
                row["settle_asset"],
                row["contract_size"],
            )
            values = {
                name: row[name]
                for name in (
                    "id",
                    "timeframe",
                    "requested_start",
                    "requested_end",
                    "started_at",
                    "last_committed_time",
                    "inserted_count",
                    "updated_count",
                    "error",
                    "finished_at",
                )
            }
            return SyncJob(
                market=market,
                dataset=SyncDataset(row["dataset"]),
                status=SyncStatus(row["status"]),
                **values,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidMarketDataError("Stored sync job is invalid") from exc

    def get_job(self, job_id: UUID) -> SyncJob | None:
        if not isinstance(job_id, UUID):
            raise TypeError("job_id must be a UUID")
        with _database_errors():
            row = (
                self._session.execute(self._job_query().where(SyncJobRow.id == job_id))
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._decode_job(row)

    def get_job_details(self, job_id: UUID) -> dict[str, Any] | None:
        if not isinstance(job_id, UUID):
            raise TypeError("job_id must be a UUID")
        with _database_errors():
            value = self._session.execute(
                select(SyncJobRow.details).where(SyncJobRow.id == job_id)
            ).scalar_one_or_none()
        if value is None:
            return None
        try:
            return _details(value)
        except ValueError as exc:
            raise InvalidMarketDataError("Stored sync details are invalid") from exc

    def save_coverage(self, coverage: CandleCoverage) -> bool:
        """Store the latest checked range, not a union of all historical checks.

        Older or equal check times do not overwrite the existing snapshot.
        Return False when ignored. CLI status for a different range must inspect
        its candles again, not extrapolate from this stored snapshot.
        """
        table = DataCoverageRow.__table__
        payload = {
            "market_id": self._market_id(coverage.market),
            "timeframe": coverage.requested.timeframe,
            "checked_start": coverage.requested.start,
            "checked_end": coverage.requested.end,
            "first_open_time": coverage.first_open_time,
            "last_open_time": coverage.last_open_time,
            "candle_count": coverage.candle_count,
            "checked_at": coverage.checked_at,
            "warnings": list(coverage.warnings),
            "missing_ranges": [
                {"start": gap.start.isoformat(), "end": gap.end.isoformat()}
                for gap in coverage.missing_ranges
            ],
        }
        statement = insert(table).values(payload)
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.market_id, table.c.timeframe],
            set_={
                name: statement.excluded[name]
                for name in payload
                if name not in ("market_id", "timeframe")
            },
            where=statement.excluded.checked_at > table.c.checked_at,
        ).returning(table.c.market_id)
        with _database_errors():
            return self._session.execute(statement).scalar_one_or_none() is not None

    def get_coverage(self, market: Market, timeframe: str) -> CandleCoverage | None:
        timeframe_delta(timeframe)
        statement = select(DataCoverageRow.__table__).where(
            DataCoverageRow.market_id == self._market_id(market),
            DataCoverageRow.timeframe == timeframe,
        )
        with _database_errors():
            row = self._session.execute(statement).mappings().one_or_none()
        if row is None:
            return None
        try:
            if not isinstance(row["missing_ranges"], list) or not isinstance(row["warnings"], list):
                raise ValueError("Coverage JSON fields must be arrays")
            requested = CandleRange(row["checked_start"], row["checked_end"], row["timeframe"])
            gaps = tuple(
                CandleRange(
                    datetime.fromisoformat(gap["start"]),
                    datetime.fromisoformat(gap["end"]),
                    row["timeframe"],
                )
                for gap in row["missing_ranges"]
            )
            return CandleCoverage(
                market,
                requested,
                row["checked_at"],
                row["candle_count"],
                row["first_open_time"],
                row["last_open_time"],
                gaps,
                tuple(row["warnings"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidMarketDataError("Stored candle coverage is invalid") from exc
