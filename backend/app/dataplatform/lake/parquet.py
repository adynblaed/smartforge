"""Parquet lake writer: staging -> validate -> atomic publish.

Layout (Specs §5.2):
    {LAKE_ROOT}/_staging/{load_id}/{table}/part-*.parquet
    {LAKE_ROOT}/published/omega/{schema}/{table}/
        snapshot_scn={scn}/load_id={load_id}/part-*.parquet + manifest.json
        increment_date={YYYY-MM-DD}/load_id={load_id}/...
    {LAKE_ROOT}/quarantine/{load_id}/...

Published files are immutable (LAKE-001); publication is a directory move,
so consumers never observe a partial dataset (SEED-005/007).
"""

from __future__ import annotations

import datetime as dt
import logging
import shutil
from collections.abc import Iterable, Iterator
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from app.dataplatform.config import PlatformSettings, get_platform_settings
from app.dataplatform.lake.manifest import LoadManifest
from app.dataplatform.oracle.metadata import InferredTable
from app.dataplatform.oracle.snapshot import SourceBoundary

logger = logging.getLogger(__name__)


class ParquetWriteResult:
    """Files and row count produced by one staged Parquet write — the exact
    figures later recorded in the load manifest (LAKE-004)."""

    def __init__(self) -> None:
        self.files: list[dict[str, object]] = []
        self.row_count = 0

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_bytes(self) -> int:
        """On-disk payload of the staged load — the figure the migration
        throughput KPIs (bytes/s, Mbps) are computed from."""
        total = 0
        for entry in self.files:
            size = entry.get("bytes", 0)
            if isinstance(size, int):
                total += size
        return total


def write_staged_load(
    batches: Iterable[pa.RecordBatch],
    schema: pa.Schema,
    *,
    load_id: str,
    table_name: str,
    settings: PlatformSettings | None = None,
) -> tuple[Path, ParquetWriteResult]:
    """Write Arrow batches to the unpublished staging area."""
    settings = settings or get_platform_settings()
    staging_dir = settings.lake_staging_dir / f"load_id={load_id}" / table_name
    staging_dir.mkdir(parents=True, exist_ok=True)

    result = ParquetWriteResult()
    target_bytes = settings.PARQUET_TARGET_FILE_MB * 1024 * 1024
    part = 0
    writer: pq.ParquetWriter | None = None
    current_path: Path | None = None
    written_in_file = 0
    rows_in_file = 0

    def _close_current() -> None:
        nonlocal writer, current_path, written_in_file, rows_in_file, part
        if writer is not None and current_path is not None:
            writer.close()
            result.files.append(
                {
                    "path": current_path.name,
                    "rows": rows_in_file,
                    "bytes": current_path.stat().st_size,
                }
            )
            part += 1
        writer = None
        current_path = None
        written_in_file = 0
        rows_in_file = 0

    for batch in batches:
        if writer is None:
            current_path = staging_dir / f"part-{part:05d}.parquet"
            writer = pq.ParquetWriter(
                current_path,
                schema,
                compression=settings.PARQUET_COMPRESSION,
                store_schema=True,
            )
        writer.write_batch(batch)
        result.row_count += batch.num_rows
        rows_in_file += batch.num_rows
        written_in_file += batch.nbytes
        if written_in_file >= target_bytes:
            _close_current()
    _close_current()

    if result.row_count == 0:
        # Still emit an empty file so the load is explicit and replayable.
        empty_path = staging_dir / "part-00000.parquet"
        pq.write_table(
            schema.empty_table(), empty_path, compression=settings.PARQUET_COMPRESSION
        )
        result.files.append(
            {"path": empty_path.name, "rows": 0, "bytes": empty_path.stat().st_size}
        )

    logger.info(
        "staged parquet load table=%s load_id=%s rows=%d files=%d",
        table_name,
        load_id,
        result.row_count,
        result.file_count,
    )
    return staging_dir, result


def validate_staged_load(staging_dir: Path, expected_rows: int) -> None:
    """Re-count rows straight from the staged files (DR-006)."""
    actual = 0
    for path in sorted(staging_dir.glob("part-*.parquet")):
        actual += pq.ParquetFile(path).metadata.num_rows
    if actual != expected_rows:
        raise RuntimeError(
            f"Staged Parquet row count {actual} != extracted count "
            f"{expected_rows} in {staging_dir}; refusing to publish."
        )


def publish_load(
    staging_dir: Path,
    inferred: InferredTable,
    boundary: SourceBoundary,
    manifest: LoadManifest,
    *,
    kind: str,  # "snapshot" | "increment"
    settings: PlatformSettings | None = None,
) -> Path:
    """Atomically move a validated staged load into the published tree."""
    settings = settings or get_platform_settings()
    contract = inferred.contract
    table_dir = contract.lake_table_dir(settings.lake_published_dir)
    if kind == "snapshot":
        partition = f"snapshot_scn={boundary.scn}"
    else:
        partition = f"increment_date={boundary.captured_at_utc.date().isoformat()}"
    final_dir = table_dir / partition / f"load_id={manifest.load_id}"
    final_dir.parent.mkdir(parents=True, exist_ok=True)

    if final_dir.exists():
        raise FileExistsError(
            f"Published load already exists: {final_dir}. Published loads are "
            "immutable — a re-run needs a new load_id (SEED-013)."
        )

    manifest.status = "published"
    manifest.published_at = dt.datetime.now(dt.timezone.utc)
    manifest.write(staging_dir)
    shutil.move(str(staging_dir), str(final_dir))
    logger.info("published load %s -> %s", manifest.load_id, final_dir)
    return final_dir


def quarantine_load(
    staging_dir: Path, reason: str, settings: PlatformSettings | None = None
) -> Path:
    settings = settings or get_platform_settings()
    settings.lake_quarantine_dir.mkdir(parents=True, exist_ok=True)
    target = settings.lake_quarantine_dir / staging_dir.parent.name / staging_dir.name
    target.parent.mkdir(parents=True, exist_ok=True)
    (staging_dir / "_quarantine_reason.txt").write_text(reason, encoding="utf-8")
    shutil.move(str(staging_dir), str(target))
    logger.warning("quarantined load dir %s (%s)", target, reason)
    return target


def iter_published_parquet(table_dir: Path) -> Iterator[Path]:
    yield from sorted(table_dir.rglob("part-*.parquet"))


def prune_snapshots(table_dir: Path, retain: int) -> list[Path]:
    """Keep the newest N snapshot partitions; remove older ones (LAKE-011)."""
    snapshots = sorted(
        (p for p in table_dir.glob("snapshot_scn=*") if p.is_dir()),
        key=lambda p: int(p.name.split("=")[1]),
        reverse=True,
    )
    removed: list[Path] = []
    for old in snapshots[retain:]:
        shutil.rmtree(old)
        removed.append(old)
        logger.info("pruned old snapshot %s", old)
    return removed
