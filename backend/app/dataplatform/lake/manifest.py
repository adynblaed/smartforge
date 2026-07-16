"""Load manifests — the authoritative evidence a load is complete.

Every published Parquet load carries a manifest.json (Specs §12.3,
Checklist LAKE-004/SEED-006). Consumers and replays trust the manifest,
never the mere presence of files.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class LoadManifest(BaseModel):
    """Evidence record for one Parquet load (LAKE-004/SEED-006).

    A load counts as complete only when its manifest says so — consumers and
    replays trust the manifest, never the mere presence of files.
    """

    load_id: str
    run_id: str
    source: dict[str, Any]  # database/schema/table/scn
    extraction: dict[str, Any]  # started_at/completed_at/row_count/file_count
    primary_key: list[str]
    cursor: dict[str, Any] | None = None  # column/lower/upper
    strategy: str
    schema_hash: str
    files: list[dict[str, Any]] = Field(default_factory=list)  # path/rows/bytes
    status: str = "staged"  # staged | published | quarantined
    published_at: dt.datetime | None = None

    def write(self, directory: Path) -> Path:
        path = directory / "manifest.json"
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def read(cls, directory: Path) -> LoadManifest:
        path = directory / "manifest.json"
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))


def find_manifests(published_table_dir: Path) -> list[LoadManifest]:
    """All published manifests for a table, newest load first."""
    manifests: list[LoadManifest] = []
    if not published_table_dir.exists():
        return manifests
    for manifest_path in sorted(
        published_table_dir.rglob("manifest.json"), reverse=True
    ):
        manifests.append(LoadManifest.read(manifest_path.parent))
    return manifests
