"""Platform-settings enforcement of known-default credentials (SEC-001).

Enforcement lives at settings load so EVERY process (scheduler, API, CLI)
is gated, not just operators who run preflight. Development warns;
anything else refuses to start.
"""

import pytest

from app.dataplatform.config import PlatformSettings

REAL = {
    "OMEGA_ORACLE_PASSWORD": "s3cret-omega",
    "WAREHOUSE_LOADER_PASSWORD": "s3cret-loader",
    "WAREHOUSE_DBT_PASSWORD": "s3cret-dbt",
    "WAREHOUSE_API_PASSWORD": "s3cret-api",
}


@pytest.mark.parametrize("known_default", ["changethis", "futureform2026", "admin"])
@pytest.mark.parametrize(
    "field",
    [
        "OMEGA_ORACLE_PASSWORD",
        "WAREHOUSE_LOADER_PASSWORD",
        "WAREHOUSE_DBT_PASSWORD",
        "WAREHOUSE_API_PASSWORD",
    ],
)
def test_known_default_refused_outside_development(
    field: str, known_default: str
) -> None:
    values = {**REAL, field: known_default}
    with pytest.raises(ValueError, match="known default"):
        PlatformSettings(PLATFORM_ENV="production", **values)
    with pytest.raises(ValueError, match="known default"):
        PlatformSettings(PLATFORM_ENV="staging", **values)


def test_known_default_warns_in_development() -> None:
    with pytest.warns(UserWarning, match="known default"):
        settings = PlatformSettings(
            PLATFORM_ENV="development",
            **{**REAL, "WAREHOUSE_API_PASSWORD": "changethis"},
        )
    assert settings.WAREHOUSE_API_PASSWORD == "changethis"


def test_real_secrets_accepted_in_production() -> None:
    settings = PlatformSettings(PLATFORM_ENV="production", **REAL)
    assert settings.PLATFORM_ENV == "production"


def test_empty_password_does_not_block_startup() -> None:
    """Empty = unprovisioned (app-only stacks serve 503s); it is preflight's
    job to fail empties outside development, not the process boot path."""
    settings = PlatformSettings(
        PLATFORM_ENV="production", **{**REAL, "OMEGA_ORACLE_PASSWORD": ""}
    )
    assert settings.OMEGA_ORACLE_PASSWORD == ""
