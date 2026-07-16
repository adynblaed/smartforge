"""Parquet lake lifecycle on the real filesystem: stage -> validate -> publish."""

from __future__ import annotations

import datetime as dt

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.dataplatform.lake.manifest import LoadManifest, find_manifests
from app.dataplatform.lake.parquet import (
    iter_published_parquet,
    prune_snapshots,
    publish_load,
    quarantine_load,
    validate_staged_load,
    write_staged_load,
)
from app.dataplatform.oracle.extractor import build_arrow_schema
from tests_dataplatform.conftest import fill_batch, make_boundary


def make_manifest(
    inferred, boundary, rows: int, files: list | None = None
) -> LoadManifest:
    contract = inferred.contract
    return LoadManifest(
        load_id=boundary.load_id,
        run_id="run_test",
        source={
            "database": contract.source_database,
            "schema": contract.source_schema,
            "table": contract.source_table,
            "scn": boundary.scn,
        },
        extraction={
            "started_at": "2026-07-15T10:00:00+00:00",
            "completed_at": "2026-07-15T10:01:00+00:00",
            "row_count": rows,
            "file_count": len(files or []),
        },
        primary_key=list(contract.primary_key),
        cursor={"column": contract.cursor_column, "lower": None, "upper": "2026-07-15"},
        strategy=contract.strategy.value,
        schema_hash=inferred.schema_hash,
        files=files or [],
    )


def stage(settings, inferred, boundary, num_batches=1, rows_per_batch=5):
    schema = build_arrow_schema(inferred)
    batches = [
        fill_batch(schema, rows_per_batch, start=i * rows_per_batch)
        for i in range(num_batches)
    ]
    return write_staged_load(
        batches,
        schema,
        load_id=boundary.load_id,
        table_name=inferred.contract.destination_name,
        settings=settings,
    )


class TestWriteStagedLoad:
    def test_writes_readable_parquet_into_staging(
        self, make_settings, machines_inferred, boundary
    ):
        settings = make_settings()
        staging_dir, result = stage(
            settings, machines_inferred, boundary, num_batches=2
        )
        assert staging_dir == (
            settings.lake_staging_dir / f"load_id={boundary.load_id}" / "machines"
        )
        assert result.row_count == 10
        assert result.file_count == 1
        parts = sorted(staging_dir.glob("part-*.parquet"))
        assert [p.name for p in parts] == ["part-00000.parquet"]
        table = pq.read_table(parts[0])
        assert table.num_rows == 10
        assert result.files[0]["rows"] == 10
        assert result.files[0]["bytes"] == parts[0].stat().st_size

    def test_rolls_to_new_file_at_target_size(
        self, make_settings, machines_inferred, boundary
    ):
        settings = make_settings(PARQUET_TARGET_FILE_MB=1)
        schema = build_arrow_schema(machines_inferred)
        # Each batch carries ~2 MB of string payload > 1 MB target -> one
        # file per batch.
        big = "x" * 20_000

        def batch(start):
            b = fill_batch(schema, 100, start=start)
            idx = schema.get_field_index("name")
            return b.set_column(idx, schema.field("name"), pa.array([big] * 100))

        staging_dir, result = write_staged_load(
            [batch(0), batch(100), batch(200)],
            schema,
            load_id=boundary.load_id,
            table_name="machines",
            settings=settings,
        )
        assert result.file_count == 3
        assert sorted(p.name for p in staging_dir.glob("part-*.parquet")) == [
            "part-00000.parquet",
            "part-00001.parquet",
            "part-00002.parquet",
        ]
        assert result.row_count == 300

    def test_zero_row_load_emits_explicit_empty_file(
        self, make_settings, machines_inferred, boundary
    ):
        settings = make_settings()
        schema = build_arrow_schema(machines_inferred)
        staging_dir, result = write_staged_load(
            [],
            schema,
            load_id=boundary.load_id,
            table_name="machines",
            settings=settings,
        )
        assert result.row_count == 0
        assert result.file_count == 1
        empty = staging_dir / "part-00000.parquet"
        assert empty.exists()
        parquet_file = pq.ParquetFile(empty)
        assert parquet_file.metadata.num_rows == 0
        # Physical file schema (read_table would add hive partition columns
        # inferred from the load_id=... path segment).
        assert parquet_file.schema_arrow.names == schema.names
        # And the explicit empty file validates cleanly.
        validate_staged_load(staging_dir, 0)


class TestValidateStagedLoad:
    def test_accepts_matching_row_count(
        self, make_settings, machines_inferred, boundary
    ):
        settings = make_settings()
        staging_dir, result = stage(settings, machines_inferred, boundary)
        validate_staged_load(staging_dir, result.row_count)

    def test_rejects_row_count_mismatch(
        self, make_settings, machines_inferred, boundary
    ):
        settings = make_settings()
        staging_dir, result = stage(settings, machines_inferred, boundary)
        with pytest.raises(RuntimeError, match="refusing to publish"):
            validate_staged_load(staging_dir, result.row_count + 1)


class TestPublishLoad:
    def test_publish_moves_atomically_and_writes_manifest(
        self, make_settings, machines_inferred, boundary
    ):
        settings = make_settings()
        staging_dir, result = stage(settings, machines_inferred, boundary)
        manifest = make_manifest(
            machines_inferred, boundary, result.row_count, result.files
        )
        final_dir = publish_load(
            staging_dir,
            machines_inferred,
            boundary,
            manifest,
            kind="snapshot",
            settings=settings,
        )
        expected = (
            settings.lake_published_dir
            / "omega"
            / "omega"
            / "machines"
            / f"snapshot_scn={boundary.scn}"
            / f"load_id={boundary.load_id}"
        )
        assert final_dir == expected
        assert not staging_dir.exists()  # moved, not copied
        assert (final_dir / "manifest.json").exists()
        published = LoadManifest.read(final_dir)
        assert published.status == "published"
        assert published.published_at is not None
        assert published.load_id == boundary.load_id
        assert list(iter_published_parquet(final_dir.parent.parent)) == sorted(
            final_dir.glob("part-*.parquet")
        )

    def test_increment_kind_partitions_by_date(
        self, make_settings, machines_inferred, boundary
    ):
        settings = make_settings()
        staging_dir, result = stage(settings, machines_inferred, boundary)
        manifest = make_manifest(machines_inferred, boundary, result.row_count)
        final_dir = publish_load(
            staging_dir,
            machines_inferred,
            boundary,
            manifest,
            kind="increment",
            settings=settings,
        )
        assert final_dir.parent.name == (
            f"increment_date={boundary.captured_at_utc.date().isoformat()}"
        )

    def test_republish_same_load_id_is_refused(
        self, make_settings, machines_inferred, boundary
    ):
        settings = make_settings()
        staging_dir, result = stage(settings, machines_inferred, boundary)
        manifest = make_manifest(machines_inferred, boundary, result.row_count)
        publish_load(
            staging_dir,
            machines_inferred,
            boundary,
            manifest,
            kind="snapshot",
            settings=settings,
        )
        # Re-stage the very same load_id and try again: immutability wins.
        staging_dir2, result2 = stage(settings, machines_inferred, boundary)
        manifest2 = make_manifest(machines_inferred, boundary, result2.row_count)
        with pytest.raises(FileExistsError, match="immutable"):
            publish_load(
                staging_dir2,
                machines_inferred,
                boundary,
                manifest2,
                kind="snapshot",
                settings=settings,
            )
        # The already-published data was not disturbed.
        published = LoadManifest.read(
            settings.lake_published_dir
            / "omega"
            / "omega"
            / "machines"
            / f"snapshot_scn={boundary.scn}"
            / f"load_id={boundary.load_id}"
        )
        assert published.status == "published"


class TestQuarantine:
    def test_quarantine_moves_load_with_reason(
        self, make_settings, machines_inferred, boundary
    ):
        settings = make_settings()
        staging_dir, _ = stage(settings, machines_inferred, boundary)
        target = quarantine_load(staging_dir, "row count mismatch", settings=settings)
        assert not staging_dir.exists()
        assert target == (
            settings.lake_quarantine_dir / f"load_id={boundary.load_id}" / "machines"
        )
        reason = (target / "_quarantine_reason.txt").read_text(encoding="utf-8")
        assert reason == "row count mismatch"
        assert list(target.glob("part-*.parquet"))


class TestPruneSnapshots:
    def test_retains_newest_n_snapshots(self, make_settings, machines_inferred):
        settings = make_settings()
        table_dir = settings.lake_published_dir / "omega" / "omega" / "machines"
        for scn in (100, 900, 2000, 10_000, 50_000):
            boundary = make_boundary(scn)
            staging_dir, result = stage(settings, machines_inferred, boundary)
            manifest = make_manifest(machines_inferred, boundary, result.row_count)
            publish_load(
                staging_dir,
                machines_inferred,
                boundary,
                manifest,
                kind="snapshot",
                settings=settings,
            )
        removed = prune_snapshots(table_dir, retain=3)
        # Numeric ordering (not lexical): 900 and 100 are the oldest.
        assert sorted(p.name for p in removed) == [
            "snapshot_scn=100",
            "snapshot_scn=900",
        ]
        remaining = sorted(p.name for p in table_dir.glob("snapshot_scn=*"))
        assert remaining == [
            "snapshot_scn=10000",
            "snapshot_scn=2000",
            "snapshot_scn=50000",
        ]

    def test_prune_is_noop_when_under_retention(self, make_settings, machines_inferred):
        settings = make_settings()
        table_dir = settings.lake_published_dir / "omega" / "omega" / "machines"
        boundary = make_boundary(123)
        staging_dir, result = stage(settings, machines_inferred, boundary)
        manifest = make_manifest(machines_inferred, boundary, result.row_count)
        publish_load(
            staging_dir,
            machines_inferred,
            boundary,
            manifest,
            kind="snapshot",
            settings=settings,
        )
        assert prune_snapshots(table_dir, retain=3) == []
        assert list(table_dir.glob("snapshot_scn=*"))


class TestManifests:
    def test_manifest_roundtrip_preserves_all_fields(self, tmp_path, machines_inferred):
        boundary = make_boundary(777)
        manifest = make_manifest(
            machines_inferred,
            boundary,
            42,
            files=[{"path": "part-00000.parquet", "rows": 42, "bytes": 1234}],
        )
        manifest.status = "published"
        manifest.published_at = dt.datetime(2026, 7, 15, 12, 0, tzinfo=dt.timezone.utc)
        manifest.write(tmp_path)
        loaded = LoadManifest.read(tmp_path)
        assert loaded == manifest
        assert loaded.model_dump() == manifest.model_dump()

    def test_find_manifests_newest_first(self, make_settings, machines_inferred):
        settings = make_settings()
        table_dir = settings.lake_published_dir / "omega" / "omega" / "machines"
        for scn in (1000, 3000, 2000):
            boundary = make_boundary(scn)
            staging_dir, result = stage(settings, machines_inferred, boundary)
            manifest = make_manifest(machines_inferred, boundary, result.row_count)
            publish_load(
                staging_dir,
                machines_inferred,
                boundary,
                manifest,
                kind="snapshot",
                settings=settings,
            )
        manifests = find_manifests(table_dir)
        assert len(manifests) == 3
        load_ids = [m.load_id for m in manifests]
        assert load_ids == sorted(load_ids, reverse=True)
        assert manifests[0].source["scn"] == 3000

    def test_find_manifests_empty_for_missing_dir(self, tmp_path):
        assert find_manifests(tmp_path / "does-not-exist") == []
