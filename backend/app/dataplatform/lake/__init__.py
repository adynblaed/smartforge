"""Canonical Parquet lake: staged writes, load manifests, DuckDB catalog.

Published Parquet files are immutable (LAKE-001), every load is evidenced by a
manifest (LAKE-004), and consumers query the lake read-only via DuckDB (DDB-003).
"""
