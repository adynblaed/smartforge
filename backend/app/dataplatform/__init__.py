"""SmartForge Data Platform.

Read-only replication of the omega (Oracle) source into a dual-target
analytics platform, per specs/Data_Warehouse_Lake_Specs.pdf:

    Oracle (read-only) -> python-oracledb thin -> Arrow -> canonical Parquet
    lake (staging -> published, manifested, load-versioned) -> dlt merge into
    PostgreSQL warehouse (control/raw_oracle/staging/intermediate/marts/api/
    audit) + DuckDB lake engine (read-only views over published Parquet)
    -> dbt (dual targets) -> FastAPI read-only data products.

Operating rule: at-least-once extraction + idempotent merge + delayed
watermark advancement. Watermarks commit only after Parquet publication,
warehouse load, and validation all succeed.
"""
