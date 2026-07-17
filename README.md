# SmartForge — Smart Factory Intelligence Platform

**v1.0.0** · Future Form Manufacturing

SmartForge is a full-stack smart-factory platform: live machine telemetry,
AI-assisted operations, a 3D digital-twin factory map, predictive
maintenance, ERP/MES integrations, a customer portal, executive
observability — and a governed **analytics data platform** that replicates
the legacy omega Oracle system into a Parquet data lake (DuckDB) and a
PostgreSQL warehouse, transformed with dbt and served through hardened
FastAPI endpoints.

> New here? Start with [`CLAUDE.md`](CLAUDE.md) — the single guide covering
> prerequisites, launch, credential testing, the service catalogue, data
> lifecycles, exchange/migration procedures, testing, and the Day-0
> deployment procedure. The formal record lives in `specs/`:
> [`ARCHITECTURE.md`](specs/ARCHITECTURE.md) (specification of record),
> [`CHECKLIST.md`](specs/CHECKLIST.md) (marked acceptance), and
> [`FEATURES.md`](specs/FEATURES.md) (per-persona feature matrix).
> Connecting the live omega Oracle source? —
> [`QUICKSTART.md`](QUICKSTART.md) (credentials → seed rehearsal → initial
> migration).

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI · SQLModel · Pydantic · PostgreSQL 18 · Redis · Qdrant |
| Data platform | python-oracledb (thin) · PyArrow/Parquet · DuckDB · dlt · dbt (dual-target) |
| Frontend | React 19 · TypeScript · Vite · TanStack Router/Query · Tailwind v4 · shadcn/ui · React Three Fiber |
| AI | Anthropic Claude (ForgeAI RAG with cited sources; deterministic offline fallback) |
| Ops | Docker Compose · Traefik (TLS, rate limits, security headers) · Prometheus · Grafana · Helm + Argo CD (`infra/`) |
| CI/CD | GitHub Actions: tests, dual dbt parse, Playwright E2E, gitleaks/pip-audit/osv security scans, staged deploys |

## Modules

Organized as the app sidebar (breadcrumbs mirror this grouping):

- **Smart Forge** — *Command Center* (executive KPIs, risk panels, global
  operations globe), *Factory Simulation* (3D digital twin with machine
  deep-links), and *ForgeAI* (RAG assistant grounded in SOPs and forge
  facts, with cited sources).
- **Machine Intelligence** — *Machines* (live console), *Work Orders*, and
  *Tickets* (master-detail maintenance alert center with serialized
  tickets, parts & inventory, SOP guidance, acknowledgement trail).
- **Factory Intelligence** — *Quality* (OEE + defect/scrap analytics) and
  *Optimizations* (config recommendations, capacity what-if, simulation studio).
- **MES** — *Services* / *Integrations* (ERP & MES sync status + event log)
  and *Incidents* (impact view + root-cause records).
- **Purchase Orders** — *Order Tracker*, *Supply Chain* (inventory,
  supplier risk, reorder recommendations, live PO operations), and
  *Quotes & Intake* (quote builder with branded PDF + PO review).
- **Software Services** — **Data Platform** (replication freshness, runs,
  reconciliation, warehouse KPIs, lake manifests, and the **Work Orders
  explorer** — a read-only query builder over the certified, UUID-keyed,
  genealogy-enriched `api.api_work_orders` contract, with a 3D genealogy
  galaxy and a Plotly EDA charts tab) and **MRP** (time-phased supply
  planning from the governed `api.api_mrp_supply_plan` mart:
  demand/supply/projected-net per item per day with shortage and
  safety-stock highlighting plus local what-if). The customer-facing
  **Portal** (`/portal`) offers order tracking and a scoped assistant.
- **Dashboards** — *Analytics*, *Admin* (user management), and *Logs*.
- **Datasources** — *Database Tables* (read-only live views with CSV
  import/export), *Forge Facts*, *SOPs*, and *Feedback* (AI-to-human
  handoffs awaiting a support response).

Borderless dark mode (shadcn palette + Future Form purple) is the default;
a light theme is available from the **Appearance** menu.

## Data platform at a glance

```
omega Oracle (READ-ONLY, verified) ──extract (SCN-consistent, keyset)──▶
Parquet lake (immutable, manifested) ──one publication feeds both──▶
   ├─▶ DuckDB catalog (read-only views)  ──▶  GET /api/v1/lake/*
   └─▶ PostgreSQL warehouse (dlt merge)  ──▶  dbt marts/api  ──▶  GET /api/v1/warehouse/*
Watermarks commit last · drift fails closed · every load reconciled & traceable
```

Formal acceptance lives in
[`specs/CHECKLIST.md`](specs/CHECKLIST.md)
(marked for v1.0.0); governance, owners, SLOs, and the exceptions register
in [`docs/data-platform.md`](docs/data-platform.md); operations in
[`runbooks/`](runbooks/).

## Quick start

```bash
cp .env.example .env        # set secrets; ANTHROPIC_API_KEY enables real ForgeAI
docker compose up --build
```

- App: http://localhost:5173 — sandbox login **smartforge@futureform.com /
  futureform2026** (superuser). Seeded accounts share
  `$SANDBOX_USER_PASSWORD`: `operator@smartforge.com`,
  `buyer@acme-robotics.com` (routes to `/portal`).
- API docs: http://localhost:8000/docs · ReDoc: http://localhost:8000/redoc
- Prometheus: http://localhost:9090 · Grafana: http://localhost:3001
  (admin / `$GRAFANA_PASSWORD`)

Verify credentials/connectivity any time:

```bash
cd backend && uv run python -m app.dataplatform.cli preflight --tolerate-unreachable
```

## Testing

```bash
# Backend app suite (no services needed)
cd backend && uv run pytest tests_smartforge -q

# Data platform suite (no services needed; mocked Oracle, real DuckDB/Parquet)
cd backend && uv run pytest tests_dataplatform -q

# Template suite (needs Postgres)
docker compose run --rm backend bash scripts/tests-start.sh

# Frontend unit + E2E
cd frontend && bun run test:unit
docker compose build playwright && CI=1 docker compose run --rm -e CI=1 playwright \
  bunx playwright test --reporter=list
```

Coverage spans every router (RBAC, customer scoping, error bounds), the
full pipeline lifecycle (watermark ordering, idempotent replay, drift
fail-closed, injection resistance, read-only proofs), dbt parse for both
engines, and 120+ Playwright E2E tests including the Data Platform page.
See [`CLAUDE.md`](CLAUDE.md) §9 for the full matrix.

## Documentation

| Document | Contents |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | The platform guide (start here) |
| [`specs/ARCHITECTURE.md`](specs/ARCHITECTURE.md) | The v1.0.0 LTS architectural record — formalizes the specs, blueprint, and acceptance checklist, with the failure-handling catalogue and runbook index |
| [`QUICKSTART.md`](QUICKSTART.md) | omega Oracle credentials, seed rehearsal, and the initial migration (with [`runbooks/initial_migration.md`](runbooks/initial_migration.md)) |
| [`specs/FEATURES.md`](specs/FEATURES.md) | v1.0.0 feature matrix by user category (GA / GA* / deferred) |
| [`development.md`](development.md) | Local development workflow |
| [`deployment.md`](deployment.md) | Compose/Traefik production deployment |
| [`infra/helm/README.md`](infra/helm/README.md) · [`infra/argocd/README.md`](infra/argocd/README.md) | Kubernetes + GitOps |
| [`docs/architecture.md`](docs/architecture.md) · [`docs/api.md`](docs/api.md) · [`docs/data-model.md`](docs/data-model.md) | Architecture, API, data model |
| [`docs/data-platform.md`](docs/data-platform.md) | Data-platform handbook (governance, SLOs, exceptions) |
| [`docs/compliance.md`](docs/compliance.md) | GDPR & SOC 2 control mapping, data-subject request procedures |
| [`backend/README.md`](backend/README.md) · [`frontend/README.md`](frontend/README.md) | Per-package development guides |
| [`release-notes.md`](release-notes.md) | Release history (v1.0.0) |

## License

MIT. Built on the excellent
[Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template).
