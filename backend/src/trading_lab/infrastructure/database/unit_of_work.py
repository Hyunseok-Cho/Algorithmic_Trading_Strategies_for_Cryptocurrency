"""Bind repositories to the same short-lived transaction."""

from contextlib import contextmanager

from trading_lab.application.ports import DataUnit
from trading_lab.infrastructure.database.engine import transaction
from trading_lab.infrastructure.database.repositories import PostgresMarketDataRepository
from trading_lab.infrastructure.database.sync_repository import PostgresSyncRepository


def data_unit_factory(session_factory):
    @contextmanager
    def unit():
        with transaction(session_factory) as session:
            yield DataUnit(PostgresMarketDataRepository(session), PostgresSyncRepository(session))

    return unit
