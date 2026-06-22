# SmartForge Architecture

SmartForge is built on the FastAPI full-stack template and extended into a
modular smart-factory platform.

## Services (logical)

| Service | Implementation |
|---|---|
| API gateway | FastAPI (`app/api/routes/*`) |
| Machine Intelligence | `app/services/machine_intelligence.py` (health scoring, alert rules, WO drafting) |
| Factory Intelligence | `app/services/factory_intelligence.py` (OEE, vision, scrap analytics) |
| Integrations | `app/services/integrations.py` (ERP/MES sync, Fiix adapter) |
| AskAI (RAG) | `app/services/askai.py` (retrieval + Claude `claude-opus-4-8`) |
| Supply Chain | `app/services/supply_chain.py` (quoting, inventory risk) |
| Observability | `app/exporters/prometheus.py` + `/api/v1/metrics` |
| Worker | `app/workers/telemetry_simulator.py` (telemetry → health → alerts → pub/sub) |

## Data flow

```
simulator ──▶ telemetry_events ──▶ health scoring ──▶ machine_health_scores
                                     │
                                     ├─▶ alert rules ──▶ alerts ──▶ work_orders ──▶ Fiix (mock)
                                     ├─▶ Redis pub/sub ──▶ WebSocket ──▶ frontend (live)
                                     └─▶ Prometheus gauges ──▶ /metrics ──▶ Grafana
```

## Frontend

React 19 + TanStack Router/Query + Tailwind v4 + shadcn/ui. The 3D digital twin
(`/factory-map`) uses React Three Fiber + drei with procedural machine models.
Internal pages live under `routes/_layout/`; the customer portal under
`routes/portal/`. A thin typed client (`src/smartforge/api.ts`) calls the API
with the same bearer token as the generated client.

## Security (spec §11)

RBAC via `User.role` (`admin/operator/maintenance/planner/customer`) with
`get_current_internal_user` / `get_current_customer_user` dependencies. Customer
routes filter every query by the caller's `customer_id` and use customer-safe
projections. Work-order approvals, AI answers, escalations, and config changes
are written to `audit_logs`.
