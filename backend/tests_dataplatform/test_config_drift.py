"""Config zero-drift guard: .env.example IS the documented default surface.

Every non-deployment-specific key in .env.example must equal the code
default in PlatformSettings / app Settings — a mismatched pair means an
operator reading the template learns the wrong behavior (CICD-013). Keys
that are inherently per-deployment (hosts, secrets, paths) are excluded
explicitly, so any NEW drift fails this test instead of shipping.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.dataplatform.config import PlatformSettings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

# Per-deployment or secret keys: values in the template are placeholders or
# environment-specific by design, never code defaults.
DEPLOYMENT_SPECIFIC = {
    "OMEGA_ORACLE_PASSWORD",
    "OMEGA_ORACLE_HOST",
    "OMEGA_ORACLE_TLS_ENABLED",  # template recommends true-when-supported
    "POSTGRES_PASSWORD",
    "POSTGRES_SERVER",
    "WAREHOUSE_LOADER_PASSWORD",
    "WAREHOUSE_DBT_PASSWORD",
    "WAREHOUSE_API_PASSWORD",
    "LAKE_ROOT",
    "DUCKDB_PATH",
}


def parse_env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip('"')
    return values


def normalize(example: str, default: object) -> object:
    """Coerce the template string to the default's type for comparison."""
    if isinstance(default, bool):
        return example.lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(example)
    if isinstance(default, float):
        return float(example)
    return example


class TestPlatformConfigDrift:
    def test_env_example_matches_code_defaults(self):
        defaults = PlatformSettings(_env_file=None)
        example = parse_env_example()
        mismatches: list[str] = []
        compared = 0
        for key, raw in example.items():
            if key in DEPLOYMENT_SPECIFIC or not hasattr(defaults, key):
                continue
            default_value = getattr(defaults, key)
            compared += 1
            try:
                example_value = normalize(raw, default_value)
            except ValueError:
                mismatches.append(f"{key}: template value {raw!r} is not parseable")
                continue
            if example_value != default_value:
                mismatches.append(
                    f"{key}: .env.example={example_value!r} != code default"
                    f" {default_value!r}"
                )
        assert not mismatches, "config drift detected:\n" + "\n".join(mismatches)
        # The guard must actually be guarding: a refactor that renames the
        # settings class or template keys should trip this, not silently
        # compare nothing.
        assert compared >= 15, f"only {compared} platform keys compared"

    def test_every_platform_tuning_key_is_documented(self):
        """The reverse direction: operator-tunable pipeline knobs must
        appear in .env.example (commented or not) so they are discoverable."""
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        for key in (
            "PLATFORM_ENV",
            "PLATFORM_METRICS_PORT",
            "PIPELINE_LOCK_TTL_SECONDS",
            "SEED_REQUIRE_CONFIRMATION",
            "API_MAX_PAGE_SIZE",
            "API_STATEMENT_TIMEOUT_MS",
            "LAKE_RETAINED_SNAPSHOTS",
            "FRESHNESS_HOURLY_WARN_MINUTES",
            "FRESHNESS_HOURLY_ERROR_MINUTES",
            "FRESHNESS_DAILY_WARN_MINUTES",
            "FRESHNESS_DAILY_ERROR_MINUTES",
        ):
            assert key in text, f"{key} missing from .env.example"


class TestAppRateLimitDrift:
    def test_rate_limit_defaults_match_template(self):
        from app.core.config import Settings

        example = parse_env_example()
        fields = Settings.model_fields
        for key in (
            "RATE_LIMIT_ENABLED",
            "RATE_LIMIT_SUPERUSER_PER_MINUTE",
            "RATE_LIMIT_INTERNAL_PER_MINUTE",
            "RATE_LIMIT_CUSTOMER_PER_MINUTE",
            "RATE_LIMIT_ANONYMOUS_PER_MINUTE",
        ):
            assert key in example, f"{key} missing from .env.example"
            default = fields[key].default
            assert normalize(example[key], default) == default, (
                f"{key}: .env.example={example[key]!r} != code default {default!r}"
            )
