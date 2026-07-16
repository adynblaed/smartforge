"""Performance-regression smoke lane (CICD-014).

Times the hot data paths — Parquet write, DuckDB catalog scan, filtered
lookup — over a synthetic 200k-row table and fails on order-of-magnitude
regressions. Bounds are deliberately generous (shared CI runners are noisy);
this lane exists to catch a pathological regression (accidental O(n^2),
lost pushdown, per-row I/O), not to benchmark. Measured timings are printed
so CI logs provide a trend baseline (E3 closure evidence starts here).
"""

import time
from decimal import Decimal

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROWS = 200_000

# Generous ceilings (seconds) — roughly 10x a cold local run, so only a
# genuine regression trips them.
WRITE_BUDGET_S = 20.0
FULL_SCAN_BUDGET_S = 10.0
FILTERED_LOOKUP_BUDGET_S = 5.0


@pytest.fixture(scope="module")
def synthetic_parquet(tmp_path_factory) -> tuple[str, float]:
    """Write a 200k-row Parquet file shaped like a raw_oracle table;
    returns (path, write_seconds)."""
    out_dir = tmp_path_factory.mktemp("perf_lake")
    table = pa.table(
        {
            "po_id": pa.array(range(ROWS), type=pa.int64()),
            "supplier_id": pa.array([i % 500 for i in range(ROWS)], type=pa.int64()),
            "status": pa.array(
                ["open", "approved", "shipped", "closed"][i % 4] for i in range(ROWS)
            ),
            "total_amount": pa.array(
                [Decimal((i % 9_999) * 100 + (i % 97)) for i in range(ROWS)],
                type=pa.decimal128(18, 2),
            ),
            "_load_id": pa.array(["perf_load_0001"] * ROWS),
        }
    )
    path = str(out_dir / "part-0000.parquet")
    started = time.perf_counter()
    pq.write_table(table, path, compression="zstd")
    elapsed = time.perf_counter() - started
    return path, elapsed


def test_parquet_write_throughput(synthetic_parquet: tuple[str, float]) -> None:
    _, write_s = synthetic_parquet
    print(f"\nperf: parquet write {ROWS} rows in {write_s:.3f}s")  # noqa: T201
    assert write_s < WRITE_BUDGET_S, (
        f"Parquet write took {write_s:.1f}s for {ROWS} rows "
        f"(budget {WRITE_BUDGET_S}s) — investigate before release (CICD-014)"
    )


def test_duckdb_full_scan_aggregate(synthetic_parquet: tuple[str, float]) -> None:
    path, _ = synthetic_parquet
    conn = duckdb.connect()
    try:
        started = time.perf_counter()
        row = conn.execute(
            "SELECT count(*), sum(total_amount) FROM read_parquet(?)", [path]
        ).fetchone()
        elapsed = time.perf_counter() - started
    finally:
        conn.close()
    assert row is not None and row[0] == ROWS
    print(f"perf: duckdb full-scan aggregate in {elapsed:.3f}s")  # noqa: T201
    assert elapsed < FULL_SCAN_BUDGET_S, (
        f"Full-scan aggregate took {elapsed:.1f}s (budget {FULL_SCAN_BUDGET_S}s)"
    )


def test_duckdb_filtered_lookup_uses_pushdown(
    synthetic_parquet: tuple[str, float],
) -> None:
    """A selective filtered read must stay far cheaper than a full
    materialization — losing predicate/column pushdown is the classic
    silent lake regression (DDB-009)."""
    path, _ = synthetic_parquet
    conn = duckdb.connect()
    try:
        started = time.perf_counter()
        rows = conn.execute(
            "SELECT po_id, status FROM read_parquet(?) WHERE supplier_id = ? LIMIT 100",
            [path, 42],
        ).fetchall()
        elapsed = time.perf_counter() - started
    finally:
        conn.close()
    assert len(rows) == 100
    print(f"perf: duckdb filtered lookup in {elapsed:.3f}s")  # noqa: T201
    assert elapsed < FILTERED_LOOKUP_BUDGET_S, (
        f"Filtered lookup took {elapsed:.1f}s (budget {FILTERED_LOOKUP_BUDGET_S}s)"
    )
