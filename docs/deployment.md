# SmartForge Deployment

## Local sandbox (Docker Compose)

```bash
cd src
docker compose up --build
```

Brings up: `db` (Postgres), `redis`, `backend` (FastAPI), `worker` (telemetry
simulator), `frontend`, `prometheus` (:9090), `grafana` (:3001, admin/admin),
plus the template `adminer`/`proxy`/`mailcatcher`.

- API docs: `http://localhost:8000/docs`
- Prometheus metrics: `http://localhost:8000/api/v1/metrics`
- Grafana: `http://localhost:3001` → "SmartForge Overview" dashboard

Set `ANTHROPIC_API_KEY` in `.env` to enable real Claude AskAI (otherwise a
deterministic offline fallback is used).

## Frontend dev

```bash
cd src/frontend
bun install            # installs three / @react-three/fiber / drei / recharts
bun run generate-client  # regenerate typed client from openapi.json (optional)
bun run dev
```

## Sandbox accounts (seeded)

Internal/customer sandbox accounts use `SANDBOX_USER_PASSWORD` (default
`changethis`, override in `.env`).

- Superuser: `smartforge@futureform.com` / `futureform2026` (admin; from `FIRST_SUPERUSER`*)
- `operator@smartforge.com` / `$SANDBOX_USER_PASSWORD` (also maintenance@, planner@)
- Customer portal: `buyer@acme-robotics.com` / `$SANDBOX_USER_PASSWORD` → `/portal`
  (also `buyer@globex-mfg.com`)

## Testing

**Backend** — isolated SmartForge suite (in-memory SQLite + FastAPI dependency
overrides; no DB or services required, never touches the sandbox data):

```bash
cd src/backend
uv run coverage run -m pytest tests_smartforge && uv run coverage report
```

Covers service-layer units (health scoring, alert rules, OEE, quoting, vision,
AskAI retrieval/fallback, integrations) and every router via `TestClient`,
including the full work-order and purchase-order lifecycles, RBAC/customer
scoping, and error-bound (404/403/422) cases. SmartForge services/routers sit at
94–100% line coverage.

The original template suite (`tests/`) runs against Postgres via
`bash scripts/tests-start.sh` — keep it separate, it resets users.

**Frontend** — unit tests (Vitest + Testing Library) and E2E (Playwright):

```bash
cd src/frontend
bun install
bun run test:unit          # vitest: api wrapper, health helpers, ChatPanel, realtime hook
bun run test               # playwright: internal flows + customer portal (needs the stack up)
```

## Production direction

See `infra/helm`, `infra/terraform`, `infra/ansible`, and `infra/argocd` for the
Kubernetes / IaC / GitOps scaffolds and the Vault secret-management notes.
