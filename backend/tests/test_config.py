"""Offline settings tests; no PostgreSQL server or exchange access is needed."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from trading_lab.config import BACKEND_DIR, Settings


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch):
    # Local shell credentials and settings must not change test outcomes.
    for field in Settings.model_fields.values():
        monkeypatch.delenv(field.validation_alias, raising=False)


def make_settings(**overrides):
    values = {
        "POSTGRES_DB": "test_trading_lab",
        "POSTGRES_USER": "test_user",
        "POSTGRES_PASSWORD": "test-only-password",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_defaults_and_reports_path_do_not_depend_on_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = make_settings()

    assert settings.postgres_host == "127.0.0.1"
    assert settings.postgres_port == 5432
    assert settings.data_start == datetime(2021, 1, 1, tzinfo=UTC)
    assert settings.reports_dir == (BACKEND_DIR / "reports").resolve()
    assert settings.fetch_max_retries == 3


def test_resolving_a_reports_path_does_not_create_it(tmp_path):
    destination = tmp_path / "not-created"
    settings = make_settings(TRADING_LAB_REPORTS_DIR=str(destination))

    assert settings.reports_dir == destination.resolve()
    assert not destination.exists()


def test_database_url_preserves_special_characters_and_masks_password():
    password = "test@pass/word:#?%"
    settings = make_settings(POSTGRES_PASSWORD=password)

    assert settings.database_url.drivername == "postgresql+psycopg"
    assert settings.database_url.password == password
    assert settings.database_url.database == "test_trading_lab"
    assert password not in repr(settings)
    assert password not in str(settings.database_url)


def test_data_start_is_converted_to_utc():
    settings = make_settings(TRADING_LAB_DATA_START="2026-10-31T02:00:00+02:00")

    assert settings.data_start == datetime(2026, 10, 31, tzinfo=UTC)
    assert settings.data_start.tzinfo is UTC


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("POSTGRES_DB", " "),
        ("POSTGRES_USER", ""),
        ("POSTGRES_HOST", " "),
        ("POSTGRES_PASSWORD", ""),
        ("POSTGRES_PASSWORD", "replace_with_a_local_password"),
        ("POSTGRES_PORT", 0),
        ("POSTGRES_PORT", 65536),
        ("TRADING_LAB_FETCH_MAX_RETRIES", -1),
        ("TRADING_LAB_FETCH_BACKOFF_SECONDS", 0),
        ("TRADING_LAB_FETCH_BACKOFF_SECONDS", "nan"),
        ("TRADING_LAB_FETCH_BACKOFF_SECONDS", "inf"),
        ("TRADING_LAB_FETCH_TIMEOUT_MS", 0),
        ("TRADING_LAB_LOG_LEVEL", "UNKNOWN"),
        ("TRADING_LAB_DATA_START", "2026-10-31T00:00:00"),
    ],
)
def test_invalid_configuration_is_rejected(key, value):
    with pytest.raises(ValidationError):
        make_settings(**{key: value})


def test_zero_retries_is_allowed():
    assert make_settings(TRADING_LAB_FETCH_MAX_RETRIES=0).fetch_max_retries == 0


def test_process_environment_overrides_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_DB=test_file_db\n"
        "POSTGRES_USER=test_user\n"
        "POSTGRES_PASSWORD=test-only-password\n"
        "POSTGRES_PORT=5433\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("POSTGRES_PORT", "5434")

    settings = Settings(_env_file=env_file)

    assert settings.postgres_db == "test_file_db"
    assert settings.postgres_port == 5434


def test_database_password_is_required():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, POSTGRES_DB="test_db", POSTGRES_USER="test_user")
