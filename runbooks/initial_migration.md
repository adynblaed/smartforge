# Runbook SOP: Initial Migration (Seed Rehearsal → Production Seed)

The formal, gated procedure for the first population of the analytics
platform from the omega Oracle source. Operator walkthrough with exact
commands: [`QUICKSTART.md`](../QUICKSTART.md). Broader go-live context:
[`CLAUDE.md`](../CLAUDE.md) §13; architectural record:
[`ARCHITECTURE.md`](../specs/ARCHITECTURE.md). Companion runbooks: `backfill.md`
(reseeding later), `rollback.md`, `operations.md`.

**Non-negotiables (from the checklist):** the extraction identity is
read-only and verified at every connect (ORA-002/003); one seed run =
one SCN boundary for all tables (SEED-002/009); staging is never visible
to consumers (SEED-005); watermarks commit only after publish + load +
reconciliation succeed (INC-005); a rehearsal never touches production
stores.

## Roles

| Role | Responsibility |
|---|---|
| Migration operator | Runs every command; owns the record |
| omega DBA | Provisions the account, watches source load during seeds |
| Data owners | Approve business validation (Gate G6) |
| Sponsor | Approves production seed window and cutover |

## Stage gates

Every gate must pass before the next stage. **Abort criteria** are listed
per gate — on abort, nothing needs cleanup beyond the stated step (the
pipeline fails closed; watermarks never advance on failure).

### G0 — Connectivity & identity (no data movement)

- `cli preflight` (strict) exits 0 against the target environment.
- The DBA has confirmed the account grants match
  `QUICKSTART.md` Part 1 (SELECT-only + flashback + SCN access, quota 0).
- **Abort if:** preflight reports `oracle.read_only: fail` — the account
  holds write privileges; do not proceed under any circumstances until the
  DBA rebuilds it.

### G1 — Discovery & plan review (no data movement)

- `cli discover` exits 0; the persisted seed plan shows, for **every**
  contracted table: `pk_verified: true`, `cursor_verified: true`,
  `blocking_issues: []`.
- Review every `warnings` entry with the table's owner; confirm with the
  DBA that each cursor column moves on **every** write path (bulk loads
  and direct-path inserts can bypass `updated_at`).
- Estimated rows are within the same order of magnitude the DBA expects
  (a wildly low count usually means a visibility/grant problem).
- **Abort if:** any blocking issue, any unverifiable PK/cursor, or an
  unmapped type — fix the contract (`config/tables.yml`) or exclude the
  table, then re-run discovery. Never widen the type mappings to force a
  table through (DCT-002 fails closed by design).

### G2 — Seed rehearsal (scratch environment; MANDATORY before first production seed)

Rehearse the full seed mechanics against **scratch stores** so the first
production seed is a repeat of something that already worked:

- Scratch isolation = three env overrides: `WAREHOUSE_DB=warehouse_rehearsal`,
  `LAKE_ROOT=<scratch>/lake`, `DUCKDB_PATH=<scratch>/catalog.duckdb`.
  Plans, watermarks, manifests, and data all land in the scratch stores —
  production stores are untouched by construction.
- Rehearse at minimum: the lookup table (`OMEGA.STATUS_LOOKUP`,
  full_replace), one merge table (`OMEGA.MACHINES`), and one
  control-totaled financial table (`OMEGA.PURCHASE_ORDERS`) so every
  strategy and every reconciliation kind (row counts, PK uniqueness,
  `control_total:*`, `source_control_total:*`) executes once.
- Gate passes when: seed status `succeeded`, all reconciliation checks
  `passed`, manifests present for each load, DuckDB scratch catalog
  queryable read-only, and `dbt build` green against the scratch
  warehouse target.
- Tear down the scratch stores afterwards (drop the rehearsal database,
  delete the scratch lake) — rehearsal artifacts must never be mistaken
  for production data.
- **Abort if:** any reconciliation check fails — diagnose before touching
  production (typical causes: type mapping, timezone semantics, source
  visibility). Rehearsal failures are cheap; production surprises are not.

### G3 — Production seed (off-peak window, DBA on notice)

- `platform-worker` is **stopped** for the whole migration (no dispatcher
  ticks compete with the seed; single-writer invariant). This is enforced,
  not just procedural: every writer entry point takes the pipeline
  single-flight lock (INC-013) — if a dispatcher tick is mid-flight,
  `cli seed` exits with a "lock held" error instead of overlapping; retry
  after the tick completes.
- Fresh `cli discover` immediately before seeding (supersedes the
  rehearsal-era plan; schema may have drifted since G1).
- Seed the **entire contracted set in one `cli seed` run** — one run
  captures one SCN boundary shared by every table, which is what makes
  the initial snapshot cross-table consistent (SEED-002/009). Use
  `--tables` only for a retry of individually failed tables (their retry
  gets a new SCN; note it in the record).
- If the log warns `flashback unavailable — seeding without AS OF SCN`,
  STOP unless the sponsor has explicitly accepted Method C (approximate
  boundary) in writing — flashback grants are the fix, not acceptance.
- Watch source impact with the DBA during the first large table; the pool
  is capped (≤4 sessions, 900 s call timeout) but the DBA has the veto.
- Record per-table durations from `control.replication_table_runs` — these
  are the official reseed benchmarks (SEED-016). The run's summary log
  line and `metrics` block (rows, bytes, duration, rows/s, Mbps, success
  rate — OBS-008) capture the totals in one place; paste them into the
  migration record.
- **Abort if:** the DBA calls load impact, or any table fails and the
  cause isn't immediately clear. A partially seeded set is safe to leave:
  published loads are immutable and consumers aren't wired yet; resume by
  reseeding the missing tables.

### G4 — Technical validation

All of the following, against production stores:

1. Seed run status `succeeded`; zero failures in the run record.
2. Every reconciliation row passed (counts, PK uniqueness, control
   totals): `SELECT * FROM audit.reconciliation_results WHERE NOT passed;`
   must return zero rows.
3. Every table has exactly one `loaded` manifest at the same `source_scn`.
4. `GET /api/v1/lake/datasets` lists every contracted view (14 at
   v1.0.0); a spot query returns rows with `_load_id` matching the
   manifests.
5. `dbt build` green on **both** targets (tests + source freshness).
- **Abort/rollback:** `runbooks/rollback.md` — but pre-cutover there is
  nothing downstream to roll back; fix and reseed the affected table.

### G5 — Serve & observe

- Backend running; `GET /api/v1/platform/health` all-ok;
  `/data-platform` page shows every table `fresh` with the seed load IDs.
- `GET /api/v1/warehouse/datasets` lists the marts/api products.

### G6 — Business validation (before enabling schedules)

- Data owners validate against legacy reports: KPI totals, financial
  sums, counts, date boundaries, representative records
  (Specs §27 step 14). Record sign-off in checklist §27 (closes E7 items
  at cutover).

### G7 — Enable steady state

- Start `platform-worker`. Enable contracts lowest-risk-first
  (CLAUDE.md §13 Phase E), one cadence tick between enablements.
- After the first clean hourly tick: freshness all green, incremental
  reconciliation passing, dbt green. The migration is complete; normal
  operations (`runbooks/operations.md`) take over.

## Migration record (keep with the ops log)

Date/window · operator · DBA contact · plan ID + fingerprint · seed SCN ·
per-table rows + durations · reconciliation summary · flashback yes/no ·
deviations/aborts · G6 sign-offs · date schedules enabled.
