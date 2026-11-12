"""Run store statements and failure-state updates, without claiming DB execution."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from tests.fixtures.scenarios import market
from tests.test_services_reporting_cli import fixture_result
from trading_lab.domain.exceptions import DataCoverageError, RepositoryError
from trading_lab.infrastructure.database.run_repository import PostgresRunStore


@pytest.fixture
def store(monkeypatch):
    session = MagicMock()

    @contextmanager
    def transaction(_):
        yield session

    monkeypatch.setattr(
        "trading_lab.infrastructure.database.run_repository.transaction", transaction
    )
    return PostgresRunStore(None), session


def compile_query(statement):
    return statement.compile(dialect=postgresql.dialect())


def test_begin_saves_all_input_and_provenance(store):
    runs, session = store
    result, _ = fixture_result()
    session.execute.return_value.scalar_one.return_value = 1
    runs.begin(result.run_id, market(), result.request, result.code_revision, result.data_quality)
    payload = compile_query(session.execute.call_args.args[0]).params
    assert payload["status"] == "running"
    assert payload["parameters"]["fee_rate_open"] == "0"
    assert payload["data_provenance"]["data_sha256"]
    assert payload["data_provenance"]["source_sha256"]


def test_complete_writes_full_result_and_queryable_trade_rows(store):
    runs, session = store
    result, _ = fixture_result()
    session.execute.return_value.scalar_one_or_none.return_value = result.run_id
    runs.complete(result)
    assert session.execute.call_count == 2
    payload = compile_query(session.execute.call_args_list[0].args[0]).params
    assert payload["status"] == "completed"
    assert payload["result_payload"]["summary"]["ending_equity"] == "1200.000000000000"
    trades = session.execute.call_args_list[1].args[1]
    assert trades[0]["net_pnl"] == 200
    assert trades[0]["run_id"] == result.run_id


def test_stale_completion_is_rejected_before_trade_insert(store):
    runs, session = store
    result, _ = fixture_result()
    session.execute.return_value.scalar_one_or_none.return_value = None
    with pytest.raises(RepositoryError):
        runs.complete(result)
    assert session.execute.call_count == 1


def test_get_deserializes_snapshot_and_handles_missing_result(store):
    runs, session = store
    result, _ = fixture_result()
    session.execute.return_value.scalar_one_or_none.return_value = result.model_dump(mode="json")
    assert runs.get(result.run_id) == result
    session.execute.return_value.scalar_one_or_none.return_value = None
    with pytest.raises(DataCoverageError):
        runs.get(result.run_id)


def test_failure_and_report_failure_are_separate_states(store):
    runs, session = store
    result, _ = fixture_result()
    runs.fail(result.run_id, "Synthetic execution failure")
    assert compile_query(session.execute.call_args.args[0]).params["status"] == "failed"
    runs.report_status(result.run_id, error="Synthetic export failure")
    payload = compile_query(session.execute.call_args.args[0]).params
    assert payload["report_status"] == "failed"
    assert "status" not in payload
