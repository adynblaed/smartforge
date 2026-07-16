"""PostgreSQL warehouse engines and bootstrap.

Separate role-scoped engines (IAM-003/PG-001):
  admin   - bootstrap only (create database/schemas/roles)
  loader  - writes control, raw_oracle, audit
  api     - read-only on marts + api views (used by FastAPI)

Warehouse schemas: control, raw_oracle, staging, intermediate, marts, api,
audit. dbt owns staging/intermediate/marts/api DDL; the loader owns
raw_oracle; bootstrap owns control/audit.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.dataplatform.config import PlatformSettings, get_platform_settings

logger = logging.getLogger(__name__)

# Every engine bounds connection establishment so an unreachable warehouse
# fails fast instead of hanging request handlers or health probes (API-011,
# PG-007). psycopg honors this as the libpq connect_timeout (seconds).
_CONNECT_ARGS = {"connect_timeout": 5}

WAREHOUSE_SCHEMAS = (
    "control",
    "raw_oracle",
    "staging",
    "intermediate",
    "marts",
    "api",
    "audit",
)


@lru_cache
def loader_engine() -> Engine:
    settings = get_platform_settings()
    return sa.create_engine(
        settings.warehouse_loader_dsn,
        pool_pre_ping=True,
        pool_size=4,
        connect_args=_CONNECT_ARGS,
    )


@lru_cache
def api_engine() -> Engine:
    settings = get_platform_settings()
    return sa.create_engine(
        settings.warehouse_api_dsn,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
        connect_args=_CONNECT_ARGS,
    )


def admin_engine(settings: PlatformSettings | None = None) -> Engine:
    settings = settings or get_platform_settings()
    return sa.create_engine(
        settings.warehouse_admin_dsn, pool_pre_ping=True, connect_args=_CONNECT_ARGS
    )


def ensure_database(settings: PlatformSettings | None = None) -> None:
    """Create the warehouse database if missing (bootstrap, idempotent)."""
    settings = settings or get_platform_settings()
    maintenance_dsn = settings._pg_dsn(
        settings.POSTGRES_USER, settings.POSTGRES_PASSWORD, "postgres"
    )
    engine = sa.create_engine(
        maintenance_dsn, isolation_level="AUTOCOMMIT", connect_args=_CONNECT_ARGS
    )
    with engine.connect() as connection:
        exists = connection.execute(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": settings.WAREHOUSE_DB},
        ).scalar()
        if not exists:
            db = _safe_pg_identifier(settings.WAREHOUSE_DB)
            connection.execute(sa.text(f'CREATE DATABASE "{db}"'))
            logger.info("created warehouse database %s", db)
    engine.dispose()


# DDL cannot take bind parameters, so bootstrap identifiers and secrets are
# quoted explicitly: identifiers against a strict allowlist, literals with
# standard-conforming quote doubling (SEC-001 — a secret containing a quote
# must neither break the DDL nor escape the literal).
_PG_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_pg_identifier(name: str) -> str:
    if not _PG_IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe PostgreSQL identifier in platform settings: {name!r}")
    return name


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _role_statements(settings: PlatformSettings) -> list[str]:
    db = _safe_pg_identifier(settings.WAREHOUSE_DB)
    roles = {
        settings.WAREHOUSE_LOADER_USER: settings.WAREHOUSE_LOADER_PASSWORD,
        settings.WAREHOUSE_DBT_USER: settings.WAREHOUSE_DBT_PASSWORD,
        settings.WAREHOUSE_API_USER: settings.WAREHOUSE_API_PASSWORD,
    }
    statements: list[str] = []
    for role, password in roles.items():
        role = _safe_pg_identifier(role)
        # The secret never sits inside the dollar-quoted block (a password
        # containing `$$` would otherwise terminate it): existence is
        # decided secret-free, then the password lands via one top-level
        # ALTER with a quote-doubled literal.
        statements.append(
            f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {_quote_literal(role)}) THEN
                    CREATE ROLE "{role}" LOGIN;
                END IF;
            END $$;
            """
        )
        statements.append(
            f'ALTER ROLE "{role}" WITH LOGIN PASSWORD {_quote_literal(password)}'
        )
        statements.append(f'GRANT CONNECT ON DATABASE "{db}" TO "{role}"')
    return statements


def _grant_statements(settings: PlatformSettings) -> list[str]:
    loader = _safe_pg_identifier(settings.WAREHOUSE_LOADER_USER)
    dbt = _safe_pg_identifier(settings.WAREHOUSE_DBT_USER)
    api = _safe_pg_identifier(settings.WAREHOUSE_API_USER)
    grants = [
        # Loader: control + raw_oracle + audit only (PG-002).
        f'GRANT USAGE, CREATE ON SCHEMA control, raw_oracle, audit TO "{loader}"',
        f'GRANT ALL ON ALL TABLES IN SCHEMA control, raw_oracle, audit TO "{loader}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA control GRANT ALL ON TABLES TO "{loader}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA raw_oracle GRANT ALL ON TABLES TO "{loader}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA audit GRANT ALL ON TABLES TO "{loader}"',
        # dbt transformer: read raw, own staging/intermediate/marts/api.
        f'GRANT USAGE ON SCHEMA raw_oracle, control TO "{dbt}"',
        f'GRANT SELECT ON ALL TABLES IN SCHEMA raw_oracle, control TO "{dbt}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA raw_oracle GRANT SELECT ON TABLES TO "{dbt}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA control GRANT SELECT ON TABLES TO "{dbt}"',
        f'GRANT USAGE, CREATE ON SCHEMA staging, intermediate, marts, api TO "{dbt}"',
        f'GRANT ALL ON ALL TABLES IN SCHEMA staging, intermediate, marts, api TO "{dbt}"',
        # API reader: marts + api + control run metadata, SELECT only (PG-003).
        f'GRANT USAGE ON SCHEMA marts, api, control, audit TO "{api}"',
        f'GRANT SELECT ON ALL TABLES IN SCHEMA marts, api, control, audit TO "{api}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA marts GRANT SELECT ON TABLES TO "{api}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA api GRANT SELECT ON TABLES TO "{api}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA control GRANT SELECT ON TABLES TO "{api}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA audit GRANT SELECT ON TABLES TO "{api}"',
        f'ALTER DEFAULT PRIVILEGES FOR ROLE "{dbt}" IN SCHEMA marts GRANT SELECT ON TABLES TO "{api}"',
        f'ALTER DEFAULT PRIVILEGES FOR ROLE "{dbt}" IN SCHEMA api GRANT SELECT ON TABLES TO "{api}"',
        f'ALTER DEFAULT PRIVILEGES FOR ROLE "{loader}" IN SCHEMA control GRANT SELECT ON TABLES TO "{api}"',
        f'ALTER DEFAULT PRIVILEGES FOR ROLE "{loader}" IN SCHEMA audit GRANT SELECT ON TABLES TO "{api}"',
    ]
    return grants


CONTROL_DDL = """
CREATE TABLE IF NOT EXISTS control.replication_watermarks (
    source_schema           text        NOT NULL,
    source_table            text        NOT NULL,
    cursor_column           text,
    committed_cursor_value  text,
    committed_source_scn    numeric,
    committed_load_id       text,
    updated_at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_schema, source_table)
);

CREATE TABLE IF NOT EXISTS control.replication_runs (
    run_id       text        PRIMARY KEY,
    kind         text        NOT NULL,           -- seed | incremental | reconcile
    status       text        NOT NULL,           -- running | succeeded | failed
    started_at   timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    detail       jsonb
);

CREATE TABLE IF NOT EXISTS control.replication_table_runs (
    run_id                  text        NOT NULL,
    load_id                 text        NOT NULL,
    source_schema           text        NOT NULL,
    source_table            text        NOT NULL,
    strategy                text        NOT NULL,
    status                  text        NOT NULL,
    source_scn              numeric,
    cursor_lower            text,
    cursor_upper            text,
    rows_extracted          bigint,
    rows_written_to_lake    bigint,
    rows_loaded_to_postgres bigint,
    rows_rejected           bigint      DEFAULT 0,
    error                   text,
    started_at              timestamptz NOT NULL DEFAULT now(),
    completed_at            timestamptz,
    PRIMARY KEY (run_id, source_schema, source_table)
);

CREATE TABLE IF NOT EXISTS control.replication_manifests (
    load_id       text        NOT NULL,
    source_schema text        NOT NULL,
    source_table  text        NOT NULL,
    source_scn    numeric,
    row_count     bigint,
    file_count    integer,
    schema_hash   text,
    status        text        NOT NULL,
    manifest      jsonb       NOT NULL,
    published_at  timestamptz,
    PRIMARY KEY (load_id, source_schema, source_table)
);

CREATE TABLE IF NOT EXISTS control.schema_versions (
    source_schema text        NOT NULL,
    source_table  text        NOT NULL,
    schema_hash   text        NOT NULL,
    columns       jsonb       NOT NULL,
    observed_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_schema, source_table, schema_hash)
);

CREATE TABLE IF NOT EXISTS control.seed_plans (
    plan_id     text        PRIMARY KEY,
    fingerprint text        NOT NULL,
    created_at  timestamptz NOT NULL,
    status      text        NOT NULL DEFAULT 'proposed',  -- proposed | confirmed | executed | superseded
    confirmed_by text,
    confirmed_at timestamptz,
    plan        jsonb       NOT NULL
);

CREATE TABLE IF NOT EXISTS audit.reconciliation_results (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id         text        NOT NULL,
    source_schema  text        NOT NULL,
    source_table   text        NOT NULL,
    check_name     text        NOT NULL,
    source_value   text,
    target_value   text,
    passed         boolean     NOT NULL,
    detail         jsonb,
    checked_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit.rejected_records (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id         text        NOT NULL,
    load_id        text        NOT NULL,
    source_schema  text        NOT NULL,
    source_table   text        NOT NULL,
    reason         text        NOT NULL,
    source_key     jsonb,
    record         jsonb,
    rejected_at    timestamptz NOT NULL DEFAULT now()
);
"""


def bootstrap_warehouse(settings: PlatformSettings | None = None) -> None:
    """Idempotent warehouse bootstrap: database, schemas, roles, control DDL."""
    settings = settings or get_platform_settings()
    ensure_database(settings)
    engine = admin_engine(settings)
    with engine.begin() as connection:
        for schema in WAREHOUSE_SCHEMAS:
            connection.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        for statement in _role_statements(settings):
            connection.execute(sa.text(statement))
        for statement in _grant_statements(settings):
            connection.execute(sa.text(statement))
        for statement in CONTROL_DDL.split(";\n\n"):
            if statement.strip():
                connection.execute(sa.text(statement))
    engine.dispose()
    logger.info("warehouse bootstrap complete (db=%s)", settings.WAREHOUSE_DB)
