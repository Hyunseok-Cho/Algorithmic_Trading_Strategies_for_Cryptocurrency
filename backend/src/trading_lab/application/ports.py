"""Storage boundaries used by application services and offline fakes."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from trading_lab.domain.interfaces import MarketDataRepository
from trading_lab.domain.models import Market
from trading_lab.domain.sync import CandleCoverage, SyncJob


class SyncStore(Protocol):
    def create_job(self, job: SyncJob, *, details: Mapping[str, Any] | None = None) -> None: ...
    def update_job(
        self, job: SyncJob, *, previous: SyncJob, details: Mapping[str, Any] | None = None
    ) -> None: ...
    def get_job(self, job_id: UUID) -> SyncJob | None: ...
    def save_coverage(self, coverage: CandleCoverage) -> bool: ...
    def get_coverage(self, market: Market, timeframe: str) -> CandleCoverage | None: ...


@dataclass(frozen=True)
class DataUnit:
    data: MarketDataRepository
    sync: SyncStore
