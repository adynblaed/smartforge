-- =============================================================================
-- Warehouse bootstrap DDL (reference copy).
-- The authoritative, idempotent bootstrap is:
--     python -m app.dataplatform.cli bootstrap
-- which creates the database, the schemas below, role grants, and the
-- control/audit tables (see backend/app/dataplatform/warehouse/postgres.py).
-- This file documents the layout for DBA review (PG-001, CICD-001).
-- =============================================================================

-- CREATE DATABASE warehouse;  -- run from the postgres maintenance DB

CREATE SCHEMA IF NOT EXISTS control;       -- pipeline state, watermarks, manifests, seed plans
CREATE SCHEMA IF NOT EXISTS raw_oracle;    -- typed source replicas + ingestion metadata (dlt-managed)
CREATE SCHEMA IF NOT EXISTS staging;       -- dbt: renamed/cast/deduped
CREATE SCHEMA IF NOT EXISTS intermediate;  -- dbt: reusable business logic
CREATE SCHEMA IF NOT EXISTS marts;         -- dbt: facts + dimensions
CREATE SCHEMA IF NOT EXISTS api;           -- dbt: stable read-only API contracts
CREATE SCHEMA IF NOT EXISTS audit;         -- reconciliation results, rejected records

-- Control/audit table DDL: see CONTROL_DDL in
-- backend/app/dataplatform/warehouse/postgres.py (kept there so the
-- bootstrap command and this document cannot drift apart silently).
