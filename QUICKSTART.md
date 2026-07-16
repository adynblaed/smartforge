# QUICKSTART — omega Oracle → SmartForge Analytics Platform (v1.0.0 LTS)

The operator walkthrough for connecting the live omega Oracle source and
completing the initial migration, end to end: **credentials → connection
testing → seed rehearsal → production seed**. The formal gated procedure
behind this walkthrough is
[`runbooks/initial_migration.md`](runbooks/initial_migration.md); the
wider go-live plan is [`CLAUDE.md`](CLAUDE.md) §13.

**Command convention** — every `cli` command below runs either way:

```bash
# On the host (backend/ dir, uv-managed env)
cd backend && uv run python -m app.dataplatform.cli <command>

# Inside the compose stack
docker compose exec backend python -m app.dataplatform.cli <command>
```

**One seeding workflow per environment** — same pipeline, three gates:

| Environment | Workflow | Source | Gate |
|---|---|---|---|
| **development** | `cli bootstrap && cli sample-seed` | Deterministic in-repo sample dataset (work-order genealogy, backlog, MRP pegging) | Refused outside `PLATFORM_ENV=development` |
| **staging / rehearsal** | Part 2 below (scratch-store overrides) | Real omega, disposable stores | Same `SEED OMEGA` confirmation |
| **production** | Part 3 below (gated SOP) | Real omega, production stores | Reviewed plan fingerprint + `SEED OMEGA` + DBA on notice |

The development sample seed runs the *real* pipeline — staged Parquet,
atomic publish + manifest, dlt merge, watermark-last, catalog refresh, dbt
build — so the Data Platform page, Work Orders explorer, and MRP page serve
genuinely seeded data with zero external dependencies. It is idempotent
(rerun any time; merges dedupe, snapshots are pruned to retention) and
every run logs the standard migration KPI line
(`pipeline sample_seed complete: 14/14 tables, N rows, X MiB in Zs — R rows/s, B Mbps, success 100%`).

---

## Part 1 — Set up the omega Oracle credentials

### 1.1 What the DBA creates (source side)

The extraction identity must be **dedicated and read-only** — never an
application owner, APEX runtime, or human account (ORA-001). Hand the omega
DBA this template:

```sql
-- Dedicated analytics extraction account (ORA-001/002)
CREATE USER omega_analytics_reader
  IDENTIFIED BY "<strong-generated-password>"
  DEFAULT TABLESPACE users
  QUOTA 0 ON users;                       -- can never stage/store anything

GRANT CREATE SESSION TO omega_analytics_reader;

-- SELECT on exactly the approved tables (config/tables.yml), nothing more:
GRANT SELECT ON omega.machines             TO omega_analytics_reader;
GRANT SELECT ON omega.work_orders          TO omega_analytics_reader;
GRANT SELECT ON omega.production_runs      TO omega_analytics_reader;
GRANT SELECT ON omega.telemetry_events     TO omega_analytics_reader;
GRANT SELECT ON omega.quality_inspections  TO omega_analytics_reader;
GRANT SELECT ON omega.defects              TO omega_analytics_reader;
GRANT SELECT ON omega.inventory_items      TO omega_analytics_reader;
GRANT SELECT ON omega.purchase_orders      TO omega_analytics_reader;
GRANT SELECT ON omega.purchase_order_lines TO omega_analytics_reader;
GRANT SELECT ON omega.suppliers            TO omega_analytics_reader;
GRANT SELECT ON omega.customers            TO omega_analytics_reader;
GRANT SELECT ON omega.sales_order_lines    TO omega_analytics_reader;
GRANT SELECT ON omega.mrp_pegging          TO omega_analytics_reader;
GRANT SELECT ON omega.status_lookup        TO omega_analytics_reader;

-- SCN-consistent seeds (strongly recommended — enables AS OF SCN):
GRANT FLASHBACK ON omega.machines             TO omega_analytics_reader;
--   ...repeat GRANT FLASHBACK for each approved table...

-- SCN capture (either one works; the pipeline probes both):
GRANT SELECT ON v_$database TO omega_analytics_reader;        -- preferred
-- or: GRANT EXECUTE ON sys.dbms_flashback TO omega_analytics_reader;

-- Optional but recommended: a resource profile so the tenant can't hurt
-- the transactional workload even in a bug scenario (ORA-007):
-- CREATE PROFILE analytics_reader_profile LIMIT
--   SESSIONS_PER_USER 6 IDLE_TIME 30 CONNECT_TIME 480;
-- ALTER USER omega_analytics_reader PROFILE analytics_reader_profile;
```

**Never grant:** any INSERT/UPDATE/DELETE/ALTER (object- or ANY-level),
CREATE TABLE, or EXECUTE on application packages. The platform *verifies*
this at every connect and refuses to run against a writable identity —
including object-level grants (`verify_read_only`, ORA-003).

While you're with the DBA, also agree: extraction windows, max concurrent
sessions, and undo retention ≥ the expected seed duration (avoids
`ORA-01555` during `AS OF SCN` seeds). Record the answers in the migration
record (this closes exception E2).

### 1.2 What you configure (our side)

In `.env` (from `.env.example`; never commit it):

```dotenv
OMEGA_ORACLE_USER=omega_analytics_reader
OMEGA_ORACLE_PASSWORD=<from your secret store>
OMEGA_ORACLE_HOST=omega-db.internal
OMEGA_ORACLE_PORT=1521
OMEGA_ORACLE_SERVICE_NAME=OMEGAPDB1     # preferred
OMEGA_ORACLE_SID=                       # only for legacy SID connects
OMEGA_ORACLE_SCHEMAS=OMEGA
OMEGA_ORACLE_TLS_ENABLED=true           # when the listener supports TCPS (E1)
OMEGA_ORACLE_POOL_MAX=4                 # stay a polite tenant
```

Kubernetes: the same keys come from the `oracle` existingSecret —
`infra/helm/README.md`.

### 1.3 Test the connection (before anything else)

```bash
cli preflight            # strict — must exit 0
```

Read the `oracle.read_only` line specifically:

| Result | Meaning | Action |
|---|---|---|
| `ok` | Connected; zero write privileges | Proceed |
| `unreachable` | Network/listener/credentials | Fix DNS/firewall/TNS with the DBA; `--tolerate-unreachable` lets other checks run meanwhile |
| `fail` | **Account can write** | STOP. DBA must rebuild the account (Part 1.1). The platform will never run with this identity |

The DBA can independently verify from the source side with the queries in
[`sql/oracle_inventory.sql`](sql/oracle_inventory.sql) (session privileges,
object grants, cursor candidates, current SCN).

---

## Part 2 — Test a seed before actually seeding (rehearsal)

Never point the first-ever seed at production stores. The rehearsal runs
the **real pipeline** — real Oracle reads, real Parquet, real merge, real
reconciliation — against disposable scratch stores. Isolation is three
environment overrides; production data, plans, and watermarks are
untouched by construction.

```bash
# Everything in Part 2 uses these overrides (compose shown; same vars for uv):
alias cli-r='docker compose exec \
  -e WAREHOUSE_DB=warehouse_rehearsal \
  -e LAKE_ROOT=/srv/data/rehearsal/lake \
  -e DUCKDB_PATH=/srv/data/rehearsal/catalog.duckdb \
  backend python -m app.dataplatform.cli'
```

### 2.1 Provision the scratch warehouse

```bash
cli-r bootstrap        # creates warehouse_rehearsal: 7 schemas, roles, control tables
cli-r preflight        # must exit 0 against the scratch stores
```

### 2.2 Discover and review the plan (no data movement)

```bash
cli-r discover         # read-only inference; persists a fingerprinted seed plan
cli-r plan             # print it
```

Review before going further — every table must show `pk_verified: true`,
`cursor_verified: true`, and `blocking_issues` must be `[]`. Walk every
`warnings` entry with the table's owner. Sanity-check `estimated_rows`
against DBA expectations.

### 2.3 Rehearse the seed on three representative tables

One table per mechanism: the full-replace lookup, a merge table, and a
control-totaled financial table (exercises `control_total:*` and
`source_control_total:*` reconciliation):

```bash
cli-r seed --tables OMEGA.STATUS_LOOKUP OMEGA.MACHINES OMEGA.PURCHASE_ORDERS
# Interactive gate: review the printed plan, type: SEED OMEGA
```

### 2.4 Verify the rehearsal

```bash
# 1. Reconciliation — every check must show passed=true (incl. control totals)
#    (sh -c so $POSTGRES_USER resolves inside the db container)
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d warehouse_rehearsal -c \
  "SELECT source_table, check_name, source_value, target_value, passed
     FROM audit.reconciliation_results ORDER BY checked_at;"'

# 2. Manifests — one 'loaded' manifest per table, all at the SAME source_scn
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d warehouse_rehearsal -c \
  "SELECT source_table, load_id, source_scn, row_count, status
     FROM control.replication_manifests;"'

# 3. Lake views open read-only and return rows
docker compose exec backend python -c "
import duckdb
c = duckdb.connect('/srv/data/rehearsal/catalog.duckdb', read_only=True)
print(c.execute('SELECT count(*) FROM raw_oracle.status_lookup').fetchone())"

# 4. dbt builds against the scratch warehouse (models over unseeded tables
#    will show empty marts — the build and tests must still be green).
#    In-container the dbt project lives at /app/dbt; on the host use ../dbt.
docker compose exec -e WAREHOUSE_DB=warehouse_rehearsal backend \
  dbt build --project-dir /app/dbt --profiles-dir /app/dbt --target warehouse
```

If a table's numbers don't reconcile here, they won't in production —
diagnose now (typical culprits: timezone semantics, NUMBER precision,
source visibility). Rehearsal failures cost nothing.

### 2.5 Tear down the rehearsal

```bash
docker compose exec db sh -c \
  'psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE warehouse_rehearsal;"'
docker compose exec backend rm -rf /srv/data/rehearsal
```

Rehearsal artifacts must never be mistaken for production data.

---

## Part 3 — The initial migration (production seed)

Follow the gated SOP — [`runbooks/initial_migration.md`](runbooks/initial_migration.md)
— of which this is the command summary. Schedule an off-peak window with
the DBA on notice.

```bash
# G3.0  No dispatcher during migration (single-writer + no competing ticks)
docker compose stop platform-worker

# G3.1  Provision + verify production stores
cli bootstrap
cli preflight                      # strict; must exit 0

# G3.2  FRESH discovery (schema may have moved since rehearsal)
cli discover && cli plan           # re-review: pk/cursor verified, no blockers

# G3.3  Seed EVERYTHING in one run — one run = one SCN boundary shared by
#       all tables (this is what makes the snapshot cross-table consistent).
cli seed                           # review plan, type: SEED OMEGA
#       If the log warns "flashback unavailable", STOP unless Method C was
#       formally accepted — the fix is the FLASHBACK grants in Part 1.1.

# G4    Technical validation (all must pass)
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d warehouse -c \
  "SELECT count(*) AS failed FROM audit.reconciliation_results WHERE NOT passed;"'  # 0
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d warehouse -c \
  "SELECT count(DISTINCT source_scn) AS boundaries
     FROM control.replication_manifests WHERE status = $$loaded$$;"'                # 1
cli dbt                            # dbt build, BOTH targets, green
cli freshness                      # every table fresh at the seed load

# G5    Serve — health + the Data Platform page
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/platform/health
#       then open /data-platform in the app: all tables fresh, seed load IDs listed

# G6    Business validation — data owners sign off vs legacy reports
#       (totals, counts, date boundaries, samples) BEFORE schedules start.

# G7    Enable steady state — schedules take over from here
docker compose start platform-worker
#       Enable contracts lowest-risk-first (CLAUDE.md §13 Phase E); after the
#       first clean hourly tick, normal operations (runbooks/operations.md) apply.
```

Record per-table durations from `control.replication_table_runs` — they
become the official reseed benchmarks — and complete the migration record
at the bottom of the SOP.

## Troubleshooting the first contact

| Symptom | Likely cause | Fix |
|---|---|---|
| `oracle.read_only: unreachable` | Listener/firewall/TNS | Verify host/port/service with DBA; `tnsping`-equivalent: `cli preflight --tolerate-unreachable` isolates it |
| `oracle.read_only: fail` | Account holds write privileges | Rebuild account per Part 1.1 — non-negotiable |
| `ORA-01555` during seed | Undo retention < seed duration | DBA raises undo retention, or seed off-peak / fewer tables per window |
| `flashback unavailable` warning | Missing FLASHBACK/SCN grants | Add grants from Part 1.1; reseed |
| Discovery blocking issue: unmapped type | Exotic column type | Review `config/type_mappings.yml` policy with data owner — never force it through |
| Reconciliation `control_total` mismatch | Precision/timezone mapping | Compare one row source vs lake; check `type_mappings.yml` numeric rules |
| Table missing from discovery | No SELECT grant / wrong schema | Cross-check grants vs `config/tables.yml`; `sql/oracle_inventory.sql` |
