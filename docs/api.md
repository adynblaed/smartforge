# SmartForge API (all under `/api/v1`)

Machine: `GET /machines`, `GET /machines/{id}`, `GET /machines/{id}/telemetry`,
`GET /machines/{id}/health`, `POST /machines/{id}/telemetry`, `POST /machines/{id}/ask`.

Alerts: `GET /alerts`, `POST /alerts/{id}/acknowledge`, `POST /alerts/{id}/resolve`.

Work orders: `GET /work-orders`, `POST /work-orders`, `POST /work-orders/from-alert/{id}`,
`POST /work-orders/{id}/approve`, `POST /work-orders/{id}/sync-fiix`.

Factory intelligence: `POST /inspection-results`, `GET /inspections`, `GET /defects`,
`GET /oee`, `GET /production-trends`, `GET /machine-configurations` (+`/approve`),
`GET /recommendations` (+`/{id}/decision`).

ERP/MES: `GET /integrations/status`, `GET /integrations/events`,
`POST /integrations/erp/sync`, `POST /integrations/mes/sync`.

Incidents: `GET/POST /incidents`, `GET/POST /incidents/{id}/rca`.

Planning: `GET /planning/capacity`, `POST /planning/simulate`.

Supply chain: `GET /inventory`, `GET /suppliers`, `GET /supply-chain/risks`,
`GET /purchase-orders`, `GET /quotes`, `POST /quotes/generate`,
`GET /jobs`, `POST /jobs`, `POST /jobs/intake`, `POST /jobs/{id}/approve`.

AskAI: `POST /ask-ai/ask`, `GET /ask-ai/documents`, `GET /ask-ai/sessions`.

Customer (customer-scoped): `GET /customer/orders`, `GET /customer/orders/{id}`,
`POST /customer/ask`, `POST /customer/escalate`, `GET /customer/escalations`,
`POST /customer/escalations/{id}/respond`.

Metrics/exec: `GET /factory/kpis`, `GET /command-center`, `GET /metrics` (Prometheus).

Realtime: `WS /ws/telemetry`, `WS /ws/orders`.
