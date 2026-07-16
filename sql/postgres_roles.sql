-- =============================================================================
-- Warehouse role separation (IAM-003 / PG-002 / PG-003) — psql template.
-- Usage: psql -v loader_pw='...' -v dbt_pw='...' -v api_pw='...' -d warehouse -f sql/postgres_roles.sql
-- The CLI bootstrap applies the same grants from env vars automatically.
-- =============================================================================

-- Loader: writes control, raw_oracle, audit — nothing else.
CREATE ROLE warehouse_loader LOGIN PASSWORD :'loader_pw';
GRANT CONNECT ON DATABASE warehouse TO warehouse_loader;
GRANT USAGE, CREATE ON SCHEMA control, raw_oracle, audit TO warehouse_loader;

-- dbt transformer: reads raw_oracle/control, owns staging/intermediate/marts/api.
CREATE ROLE warehouse_transformer LOGIN PASSWORD :'dbt_pw';
GRANT CONNECT ON DATABASE warehouse TO warehouse_transformer;
GRANT USAGE ON SCHEMA raw_oracle, control TO warehouse_transformer;
GRANT SELECT ON ALL TABLES IN SCHEMA raw_oracle, control TO warehouse_transformer;
GRANT USAGE, CREATE ON SCHEMA staging, intermediate, marts, api TO warehouse_transformer;

-- API reader: SELECT on marts/api (+ control/audit run metadata). Read-only.
CREATE ROLE warehouse_api_reader LOGIN PASSWORD :'api_pw';
GRANT CONNECT ON DATABASE warehouse TO warehouse_api_reader;
GRANT USAGE ON SCHEMA marts, api, control, audit TO warehouse_api_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA marts, api, control, audit TO warehouse_api_reader;

-- Default privileges so future tables inherit the same separation.
ALTER DEFAULT PRIVILEGES IN SCHEMA raw_oracle GRANT SELECT ON TABLES TO warehouse_transformer;
ALTER DEFAULT PRIVILEGES IN SCHEMA control GRANT SELECT ON TABLES TO warehouse_transformer, warehouse_api_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA audit GRANT SELECT ON TABLES TO warehouse_api_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE warehouse_transformer IN SCHEMA marts, api GRANT SELECT ON TABLES TO warehouse_api_reader;

-- Negative test (IAM-013): as warehouse_api_reader, all of these MUST fail:
--   INSERT INTO marts.dim_machines DEFAULT VALUES;
--   CREATE TABLE api.x (i int);
--   SELECT * FROM raw_oracle.customers;
