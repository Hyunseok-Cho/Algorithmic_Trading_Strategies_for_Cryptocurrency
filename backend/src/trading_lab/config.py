"""Load local CLI settings without opening a DB connection or creating files."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

# This source checkout is the local development workspace.
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Read backend/.env; process environment variables take precedence.

    Construct this at CLI execution time, never at import time. Commands that
    do not need configuration (such as strategy list) need not construct it.
    """

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    postgres_db: str = Field(min_length=1, validation_alias="POSTGRES_DB")
    postgres_user: str = Field(min_length=1, validation_alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(validation_alias="POSTGRES_PASSWORD")
    postgres_host: str = Field(default="127.0.0.1", min_length=1, validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, ge=1, le=65535, validation_alias="POSTGRES_PORT")

    reports_dir: Path = Field(default=Path("reports"), validation_alias="TRADING_LAB_REPORTS_DIR")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="TRADING_LAB_LOG_LEVEL"
    )
    data_start: AwareDatetime = Field(
        default=datetime(2021, 1, 1, tzinfo=UTC), validation_alias="TRADING_LAB_DATA_START"
    )
    fetch_max_retries: int = Field(
        default=3, ge=0, validation_alias="TRADING_LAB_FETCH_MAX_RETRIES"
    )
    fetch_backoff_seconds: float = Field(
        default=1.0,
        gt=0,
        allow_inf_nan=False,
        validation_alias="TRADING_LAB_FETCH_BACKOFF_SECONDS",
    )
    fetch_timeout_ms: int = Field(
        default=30000, gt=0, validation_alias="TRADING_LAB_FETCH_TIMEOUT_MS"
    )

    @field_validator("postgres_db", "postgres_user", "postgres_host")
    @classmethod
    def reject_blank_names(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Database name, user and host must not be blank")
        return value

    @field_validator("postgres_password")
    @classmethod
    def require_local_password(cls, value: SecretStr) -> SecretStr:
        password = value.get_secret_value()
        if not password.strip() or password == "replace_with_a_local_password":
            raise ValueError("Set a non-empty local database password in backend/.env")
        return value

    @field_validator("data_start")
    @classmethod
    def normalize_data_start(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_validator("reports_dir")
    @classmethod
    def resolve_reports_dir(cls, value: Path) -> Path:
        # Resolve only; the report service creates output directories when needed.
        value = value.expanduser()
        return (value if value.is_absolute() else BACKEND_DIR / value).resolve()

    @property
    def database_url(self) -> URL:
        """Build a psycopg URL safely, including passwords containing @ or /."""
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )
