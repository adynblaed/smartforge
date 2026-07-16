"""Parquet -> PostgreSQL raw loading via dlt (Specs §15, preferred pattern).

dlt provides the merge machinery (staging tables + PK merge), retries, and
load packages; extraction is our own SCN-bounded Oracle->Parquet step, so
the pipeline reads *published* Parquet only. A failed destination therefore
replays from the lake without touching Oracle again (DR-005).

Idempotency / ordering:
  * merge disposition keyed on the contract primary key makes replays
    idempotent (INC-004);
  * loads for one table are applied strictly in load_id order and a replay
    of an older load is refused unless it is the newest applied load for the
    table (INC-006) — enforced in `assert_load_order`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

import dlt
import pyarrow.parquet as pq
import sqlalchemy as sa

from app.dataplatform.config import PlatformSettings, get_platform_settings
from app.dataplatform.lake.manifest import LoadManifest
from app.dataplatform.registry import SyncStrategy, TableContract
from app.dataplatform.warehouse.postgres import loader_engine

logger = logging.getLogger(__name__)


class LoadOrderError(RuntimeError):
    """An older load would have overwritten newer warehouse state."""


def assert_load_order(contract: TableContract, manifest: LoadManifest) -> None:
    """Refuse to apply a load older than what the warehouse already has."""
    engine = loader_engine()
    with engine.connect() as connection:
        newest = connection.execute(
            sa.text(
                """
                SELECT max(source_scn) FROM control.replication_manifests
                 WHERE source_schema = :schema AND source_table = :table
                   AND status = 'loaded'
                """
            ),
            {"schema": contract.source_schema, "table": contract.source_table},
        ).scalar()
    load_scn = int(manifest.source["scn"])
    if newest is not None and load_scn < int(newest):
        raise LoadOrderError(
            f"Load {manifest.load_id} (scn={load_scn}) is older than already-"
            f"loaded scn={newest} for {contract.qualified_name}; replaying it "
            "would regress newer records (INC-006). Use a full reseed instead."
        )


def _parquet_rows(load_dir: Path) -> Iterator[Any]:
    """Yield Arrow record batches from every part file of a published load."""
    for part in sorted(load_dir.glob("part-*.parquet")):
        parquet_file = pq.ParquetFile(part)
        yield from parquet_file.iter_batches(batch_size=50_000)


def load_published_parquet(
    contract: TableContract,
    load_dir: Path,
    manifest: LoadManifest,
    *,
    settings: PlatformSettings | None = None,
) -> int:
    """Load one published Parquet load into raw_oracle.<destination_name>."""
    settings = settings or get_platform_settings()
    assert_load_order(contract, manifest)

    write_disposition: Literal["replace", "merge"] = (
        "replace" if contract.strategy is SyncStrategy.full_replace else "merge"
    )

    resource = dlt.resource(
        _parquet_rows(load_dir),
        name=contract.destination_name,
        primary_key=[c.lower() for c in contract.primary_key],
        write_disposition=write_disposition,
    )

    pipeline = dlt.pipeline(
        pipeline_name=f"omega_raw_{contract.destination_name}",
        destination=dlt.destinations.postgres(
            credentials=settings.warehouse_loader_dsn.replace(
                "postgresql+psycopg://", "postgresql://"
            ),
            replace_strategy="insert-from-staging",
        ),
        dataset_name="raw_oracle",
    )
    info = pipeline.run(resource)
    rows_loaded = manifest.extraction.get("row_count", 0)
    logger.info(
        "dlt load complete table=%s load_id=%s disposition=%s packages=%d",
        contract.destination_name,
        manifest.load_id,
        write_disposition,
        len(info.load_packages),
    )
    record_manifest_loaded(contract, manifest)
    return int(rows_loaded)


def record_manifest_loaded(contract: TableContract, manifest: LoadManifest) -> None:
    engine = loader_engine()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO control.replication_manifests
                    (load_id, source_schema, source_table, source_scn,
                     row_count, file_count, schema_hash, status, manifest,
                     published_at)
                VALUES
                    (:load_id, :schema, :table, :scn, :rows, :files,
                     :schema_hash, 'loaded', CAST(:manifest AS jsonb),
                     :published_at)
                ON CONFLICT (load_id, source_schema, source_table)
                DO UPDATE SET status = 'loaded', manifest = EXCLUDED.manifest
                """
            ),
            {
                "load_id": manifest.load_id,
                "schema": contract.source_schema,
                "table": contract.source_table,
                "scn": int(manifest.source["scn"]),
                "rows": manifest.extraction.get("row_count", 0),
                "files": manifest.extraction.get("file_count", 0),
                "schema_hash": manifest.schema_hash,
                "manifest": manifest.model_dump_json(),
                "published_at": manifest.published_at,
            },
        )


def warehouse_row_count(destination_name: str) -> int | None:
    engine = loader_engine()
    with engine.connect() as connection:
        try:
            return connection.execute(
                sa.text(
                    f'SELECT count(*) FROM raw_oracle."{destination_name}"'  # noqa: S608
                )
            ).scalar()
        except sa.exc.ProgrammingError:
            return None


def mark_deleted_keys(
    contract: TableContract, source_keys: set[tuple[Any, ...]]
) -> int:
    """Soft-mark warehouse rows whose keys vanished from the source (§17.2)."""
    engine = loader_engine()
    pk_cols = [c.lower() for c in contract.primary_key]
    select_cols = ", ".join(f'"{c}"' for c in pk_cols)
    table = contract.destination_name
    deleted = 0
    with engine.begin() as connection:
        rows = connection.execute(
            sa.text(
                f'SELECT {select_cols} FROM raw_oracle."{table}" '  # noqa: S608
                "WHERE NOT coalesce(_is_deleted, false)"
            )
        ).fetchall()
        missing = [tuple(row) for row in rows if tuple(row) not in source_keys]
        for key in missing:
            predicate = " AND ".join(f'"{c}" = :k{i}' for i, c in enumerate(pk_cols))
            binds = {f"k{i}": v for i, v in enumerate(key)}
            connection.execute(
                sa.text(
                    f'UPDATE raw_oracle."{table}" '  # noqa: S608
                    "SET _is_deleted = true "
                    f"WHERE {predicate}"
                ),
                binds,
            )
            deleted += 1
    if deleted:
        logger.info(
            "delete reconciliation marked %d rows deleted in raw_oracle.%s",
            deleted,
            table,
        )
    return deleted
