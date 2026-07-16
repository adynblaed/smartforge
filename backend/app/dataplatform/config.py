"""Data-platform settings.

Separate from app.core.config.Settings so the analytical platform can be
configured, deployed, and secured independently of the transactional app.
All credentials come from the environment (never from the repo); the omega
Oracle account MUST be a dedicated read-only extraction identity (ORA-001/2).
"""

from __future__ import annotations

import warnings
from functools import lru_cache
from pathlib import Path

from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


class PlatformSettings(BaseSettings):
    """Environment-driven configuration for the analytics platform.

    Credentials are never stored in the repo, and the omega Oracle identity
    must be the dedicated read-only extraction account (ORA-001/ORA-002).
    """

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Omega (Oracle) source — READ-ONLY. Thin mode, no Instant Client.
    # ------------------------------------------------------------------
    OMEGA_ORACLE_USER: str = "omega_analytics_reader"
    OMEGA_ORACLE_PASSWORD: str = ""
    OMEGA_ORACLE_HOST: str = "localhost"
    OMEGA_ORACLE_PORT: int = 1521
    OMEGA_ORACLE_SERVICE_NAME: str = "OMEGAPDB1"
    # Legacy SID connect descriptor; leave empty to use SERVICE_NAME.
    OMEGA_ORACLE_SID: str = ""
    OMEGA_ORACLE_SCHEMAS: str = "OMEGA"
    OMEGA_ORACLE_TLS_ENABLED: bool = False
    OMEGA_ORACLE_POOL_MIN: int = 1
    OMEGA_ORACLE_POOL_MAX: int = 4
    OMEGA_ORACLE_CALL_TIMEOUT_SECONDS: int = 900
    OMEGA_ORACLE_FETCH_ARRAYSIZE: int = 50_000

    # ------------------------------------------------------------------
    # Canonical Parquet lake + DuckDB catalog
    # ------------------------------------------------------------------
    LAKE_ROOT: Path = Path("./data/lake")
    DUCKDB_PATH: Path = Path("./data/catalog/smartforge_lake.duckdb")
    DUCKDB_MEMORY_LIMIT: str = "2GB"
    DUCKDB_THREADS: int = 4
    PARQUET_COMPRESSION: str = "zstd"
    PARQUET_TARGET_FILE_MB: int = 256
    LAKE_RETAINED_SNAPSHOTS: int = 3

    # ------------------------------------------------------------------
    # PostgreSQL warehouse (separate database, role-separated identities)
    # ------------------------------------------------------------------
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"  # admin/bootstrap only
    POSTGRES_PASSWORD: str = ""
    WAREHOUSE_DB: str = "warehouse"
    WAREHOUSE_LOADER_USER: str = "warehouse_loader"
    WAREHOUSE_LOADER_PASSWORD: str = ""
    WAREHOUSE_DBT_USER: str = "warehouse_transformer"
    WAREHOUSE_DBT_PASSWORD: str = ""
    WAREHOUSE_API_USER: str = "warehouse_api_reader"
    WAREHOUSE_API_PASSWORD: str = ""

    # ------------------------------------------------------------------
    # Pipeline behaviour
    # ------------------------------------------------------------------
    PLATFORM_ENV: str = "development"
    PIPELINE_LOCK_TTL_SECONDS: int = 3600
    # Prometheus scrape port for the long-lived platform-worker (pipeline
    # throughput/duration/success metrics); 0 disables the endpoint.
    PLATFORM_METRICS_PORT: int = 9108
    SEED_REQUIRE_CONFIRMATION: bool = True
    FRESHNESS_HOURLY_WARN_MINUTES: int = 75
    FRESHNESS_HOURLY_ERROR_MINUTES: int = 120
    FRESHNESS_DAILY_WARN_MINUTES: int = 1560  # 26 h
    FRESHNESS_DAILY_ERROR_MINUTES: int = 1800  # 30 h
    API_MAX_PAGE_SIZE: int = 1000
    API_STATEMENT_TIMEOUT_MS: int = 15_000

    # Known-default values that must never reach a shared environment
    # (mirrors app.core.config; SEC-001/IAM-002). Empty passwords are handled
    # separately: `cli preflight` fails them outside development, but they do
    # not block process start (an app-only staging stack may legitimately run
    # without the platform provisioned — endpoints then answer 503).
    _INSECURE_DEFAULTS = frozenset({"changethis", "futureform2026", "admin"})

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        """Refuse known-default platform credentials outside development.

        Enforcement at settings load means every process (scheduler, API,
        CLI) is gated — not only operators who remember to run preflight.
        """
        for name, value in (
            ("OMEGA_ORACLE_PASSWORD", self.OMEGA_ORACLE_PASSWORD),
            ("WAREHOUSE_LOADER_PASSWORD", self.WAREHOUSE_LOADER_PASSWORD),
            ("WAREHOUSE_DBT_PASSWORD", self.WAREHOUSE_DBT_PASSWORD),
            ("WAREHOUSE_API_PASSWORD", self.WAREHOUSE_API_PASSWORD),
        ):
            if value in self._INSECURE_DEFAULTS:
                message = (
                    f'The value of {name} is "{value}" (a known default); '
                    "set a real secret before deploying (SEC-001)."
                )
                if self.PLATFORM_ENV == "development":
                    warnings.warn(message, stacklevel=1)
                else:
                    raise ValueError(message)
        return self

    def _pg_dsn(self, user: str, password: str, database: str) -> str:
        return (
            f"postgresql+psycopg://{user}:{password}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{database}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def warehouse_admin_dsn(self) -> str:
        return self._pg_dsn(
            self.POSTGRES_USER, self.POSTGRES_PASSWORD, self.WAREHOUSE_DB
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def warehouse_loader_dsn(self) -> str:
        return self._pg_dsn(
            self.WAREHOUSE_LOADER_USER,
            self.WAREHOUSE_LOADER_PASSWORD,
            self.WAREHOUSE_DB,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def warehouse_dbt_dsn(self) -> str:
        return self._pg_dsn(
            self.WAREHOUSE_DBT_USER, self.WAREHOUSE_DBT_PASSWORD, self.WAREHOUSE_DB
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def warehouse_api_dsn(self) -> str:
        return self._pg_dsn(
            self.WAREHOUSE_API_USER, self.WAREHOUSE_API_PASSWORD, self.WAREHOUSE_DB
        )

    @property
    def oracle_dsn_params(self) -> dict[str, str | int]:
        """Connection params for oracledb.makedsn / ConnectParams."""
        params: dict[str, str | int] = {
            "host": self.OMEGA_ORACLE_HOST,
            "port": self.OMEGA_ORACLE_PORT,
        }
        if self.OMEGA_ORACLE_SID:
            params["sid"] = self.OMEGA_ORACLE_SID
        else:
            params["service_name"] = self.OMEGA_ORACLE_SERVICE_NAME
        return params

    @property
    def lake_staging_dir(self) -> Path:
        return self.LAKE_ROOT / "_staging"

    @property
    def lake_published_dir(self) -> Path:
        return self.LAKE_ROOT / "published"

    @property
    def lake_quarantine_dir(self) -> Path:
        return self.LAKE_ROOT / "quarantine"

    @property
    def repo_root(self) -> Path:
        # backend/app/dataplatform/config.py -> repo root is three levels up
        # from the backend directory that contains this package.
        return Path(__file__).resolve().parents[3]

    @property
    def tables_registry_path(self) -> Path:
        return self.repo_root / "config" / "tables.yml"

    @property
    def type_mappings_path(self) -> Path:
        return self.repo_root / "config" / "type_mappings.yml"

    @property
    def generated_config_dir(self) -> Path:
        return self.repo_root / "config" / "generated"

    @property
    def dbt_project_dir(self) -> Path:
        return self.repo_root / "dbt"


@lru_cache
def get_platform_settings() -> PlatformSettings:
    return PlatformSettings()
