# SmartForge Frontend

The SmartForge web console: a factory-operations SPA covering machine intelligence, MES observability, purchase orders, the data platform, and a customer portal. Platform-wide guidance: [`../CLAUDE.md`](../CLAUDE.md); the v1.0.0 LTS specification of record: [`../specs/ARCHITECTURE.md`](../specs/ARCHITECTURE.md) (§4.7 covers these frontend surfaces).

## Stack

- [Vite](https://vitejs.dev/) + [React 19](https://react.dev/) + [TypeScript](https://www.typescriptlang.org/)
- [TanStack Router](https://tanstack.com/router) (file-based routes in `src/routes`, generated tree in `src/routeTree.gen.ts`)
- [TanStack Query](https://tanstack.com/query) for all server state
- [Tailwind CSS v4](https://tailwindcss.com/) + [shadcn/ui](https://ui.shadcn.com/) primitives (`src/components/ui`), dark-mode-first
- [Recharts](https://recharts.org/) dashboards, [react-three-fiber](https://docs.pmnd.rs/react-three-fiber) 3D factory simulation
- [Biome](https://biomejs.dev/) for lint/format, [Vitest](https://vitest.dev/) + [Playwright](https://playwright.dev/) for tests

## Prerequisites

- [Bun](https://bun.sh/) (preferred) or [Node.js](https://nodejs.org/) ≥ 20 with npm
- The backend API running at `http://localhost:8000` (see the repo root `compose.yml`)

## Commands

| Task | Bun | npm |
| --- | --- | --- |
| Install | `bun install` | `npm install` |
| Dev server (http://localhost:5173) | `bun run dev` | `npm run dev` |
| Production build | `bun run build` | `npm run build` |
| Lint / format | `bun run lint` | `npm run lint` |
| Regenerate route tree | `bun run routes:generate` | `npm run routes:generate` |
| Regenerate API SDK | `bun run generate-client` | `npm run generate-client` |
| Unit tests | `bun run test:unit` | `npm run test:unit` |
| E2E tests | `bunx playwright test` | `npx playwright test` |

`build` runs `tsr generate && tsc -p tsconfig.build.json && vite build` — the route tree and typecheck are part of every build.

## Routes

Auth levels: **public** (no session), **internal** (any signed-in staff user — `/_layout` validates the token against `GET /users/me` and bounces customers to `/portal`), **superuser** (internal + `is_superuser`), **customer** (customer-role account, portal shell).

All endpoints below are under `/api/v1`.

### Auth & legal (public)

| Path | Title | Purpose | Backend |
| --- | --- | --- | --- |
| `/login` | Log In - SmartForge | Sign in | `POST /login/access-token` |
| `/signup` | Sign Up - SmartForge | Self-registration | `POST /users/signup` |
| `/recover-password` | Recover Password - SmartForge | Request reset email | `POST /password-recovery/{email}` |
| `/reset-password` | Reset Password - SmartForge | Set new password from token | `POST /reset-password` |
| `/privacy` | Privacy Policy - Future Form Manufacturing | Static policy page | — |
| `/terms` | Terms & Conditions - Future Form Manufacturing | Static terms page | — |

### Internal app (`/_layout` shell: sidebar, breadcrumbs, ForgeAI agent)

| Path | Title | Purpose | Backend |
| --- | --- | --- | --- |
| `/` | Smart Forge — Home | Mission-control launchpad over the nav groups | — |
| `/command-center` | Command Center - SmartForge | Fleet KPIs, at-risk machines, live overview | `GET /command-center`, `GET /purchase-orders` |
| `/factory-map` | Factory Simulation - SmartForge | 3D factory floor with live telemetry panels | `GET /machines/`, `/inventory`, `/purchase-orders`, `/machines/{id}/telemetry` |
| `/ask-ai` | ForgeAI - Smart Forge | RAG assistant over factory knowledge | `POST /ask-ai/forge` |
| `/machines` | Machines - SmartForge | Machine console: telemetry, alerts, tickets | `GET /machines/`, `/machines/{id}/telemetry`, `/alerts/`, `POST /tickets/from-alert/{id}` |
| `/work-orders` | Work Orders - SmartForge | Work-order queue + approve/deny actions | `GET /work-orders/`, `POST /work-orders/{id}/{action}` |
| `/tickets` | Tickets - SmartForge | Maintenance alert center with SOP guidance | `GET /tickets/`, `/tickets/{id}`, `POST .../acknowledge`, `.../notes`, `.../status` |
| `/quality` | Quality - SmartForge | OEE + defect analytics, inspections | `GET /oee`, `/defects`, `POST /inspection-results`, `/defects/{id}/correlate` |
| `/optimization` | Optimizations - SmartForge | Config recommendations + capacity what-ifs | `GET /machine-configurations`, `/recommendations`, `POST /planning/simulate` |
| `/services` | Services - Smart Forge | Live service health board with uptime ticker | `GET /services/` |
| `/integrations` | Integrations - SmartForge | ERP/MES sync status + manual sync triggers | `GET /integrations/status`, `/integrations/events`, `/factory/kpis`, `POST /integrations/{sys}/sync` |
| `/incidents` | Incidents - SmartForge | Incident impact + RCA records | `GET /incidents/`, `/factories`, `/tickets/by-incident`, `/incidents/{id}/rca` |
| `/order-tracker` | Order Tracker - SmartForge | Purchase orders joined to customer orders | `GET /purchase-orders`, `/inventory`, `/suppliers` |
| `/supply-chain` | Supply Chain - SmartForge | Inventory risk + supplier health + reorders | `GET /inventory`, `/supply-chain/risks`, `/suppliers`, `POST /supply-chain/reorders` |
| `/quotes` | Quotes & Intake - Smart Forge | Order intake + PO builder | `GET /quotes`, `POST /quotes/generate` |
| `/feedback` | Feedback - SmartForge | User feedback triage + responses (AI-to-human handoffs) | `GET /customer/escalations`, `POST /customer/escalations/{id}/respond` |
| `/analytics` | Analytics - SmartForge | Cross-domain dashboards | `GET /command-center`, `/oee`, `/machines/` |
| `/admin` | Admin - SmartForge | User management (**superuser**) | generated SDK: `UsersService` (`/users/`) |
| `/logs` | Logs - Smart Forge | Per-service log console incl. audit trail | `GET /logs/services`, `/logs/{service}` |
| `/datasources` | Datasources - SmartForge | Read-only live views over production tables + CSV import/export | domain list endpoints, `GET /datasources/table/{name}`, `/datasources/export`, `POST /datasources/import` |
| `/eda` | EDA - SmartForge | Exploratory Data Analysis: replication freshness, runs, reconciliation, warehouse marts/KPIs, lake catalog + manifests, and the Work Orders explorer (3D genealogy galaxy, charts, and a read-only query builder over the certified genealogy contract) | `GET /platform/health`, `/platform/freshness`, `/platform/replication/tables`, `/platform/replication/runs`, `/platform/reconciliation`, `/warehouse/datasets`, `/warehouse/datasets/work_orders`, `/warehouse/kpis`, `/lake/datasets`, `/lake/loads` |
| `/mrp` | MRP - SmartForge | Time-phased supply planning grid (demand/supply/projected net per item per day, shortage + safety-stock highlighting, local what-if) | `GET /warehouse/datasets/mrp_supply_plan` |
| `/knowledge-bases` | Forge Facts - Smart Forge | Curated RAG facts CRUD + reindex | `GET/POST/PATCH/DELETE /ask-ai/knowledge-bases`, `POST .../sync` |
| `/sops` | SOPs - Smart Forge | Chaptered standard operating procedures | `GET /sops/`, `GET/PATCH /sops/{code}` |
| `/settings` | Settings - SmartForge | Profile, password, danger zone | generated SDK: `UsersService` |
| `/items` | Items - SmartForge | Template demo CRUD (kept from the FastAPI template) | generated SDK: `ItemsService` (`/items/`) |

The `/eda` sections degrade gracefully: when the platform stores are not provisioned (endpoints return 503), each section independently renders a "Data platform not provisioned" empty state pointing at `runbooks/` instead of crashing.

### Customer portal (`/portal` shell, customer accounts)

| Path | Title | Purpose | Backend |
| --- | --- | --- | --- |
| `/portal` | My Orders - SmartForge | Customer's order list | `GET /customer/orders` |
| `/portal/ask` | Order Assistant - SmartForge | Scoped AI assistant + human escalation | `POST /customer/ask`, `POST /customer/escalate` |
| `/portal/orders/$orderId` | Order - SmartForge | Live order detail | `GET /customer/orders/{id}`, WS `/ws/orders` |

## API clients

Two clients coexist — pick deliberately:

1. **Generated SDK** (`src/client/**`, axios-based, generated by `@hey-api/openapi-ts`): used by the FastAPI-template routes — auth (`LoginService`, `UsersService`), `/admin`, `/settings`, `/items`. Do not hand-edit; regenerate it (below).
2. **`sf` wrapper** (`src/smartforge/api.ts`): a thin typed `fetch` wrapper sharing the same base URL and bearer token. This is the established pattern for **all SmartForge endpoints**, including the data platform (`/platform`, `/warehouse`, `/lake`). Response types live next to the pages or in `src/smartforge/*Types.ts` (e.g. `platformTypes.ts` mirrors the backend handlers). It also provides `blob`/`upload` helpers and `wsUrl()` for authenticated WebSockets.

New SmartForge features should use `sf` — no client regeneration required.

### Regenerating the SDK

`openapi-ts.config.ts` reads `./openapi.json` at the frontend root:

```bash
# with the backend running
curl http://localhost:8000/api/v1/openapi.json -o openapi.json
bun run generate-client        # or: npm run generate-client
```

Or run `bash ./scripts/generate-client.sh` from the repo root (activates the backend venv and does both steps).

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_URL` | `http://localhost:8000` | API base URL used by both clients (set in `frontend/.env` for remote APIs) |

## Testing

**Unit (Vitest + Testing Library, jsdom)** — `tests-unit/`, configured by `vitest.config.ts` (kept separate from `vite.config.ts` so the router plugin doesn't scan routes during tests):

```bash
bun run test:unit          # or: npm run test:unit / npx vitest run
bun run test:unit:coverage # coverage over src/smartforge/**
```

Covers the pure helpers and presentational pieces in `src/smartforge/` (API wrapper, markdown, chat panel, data-platform formatting/badges, the Work Orders query-builder grammar, the MRP grid/net-inventory/what-if math, realtime hook).

**End-to-end (Playwright)** — `tests/`, configured by `playwright.config.ts`. A `setup` project logs in as the first superuser (`auth.setup.ts`) and every spec reuses that storage state. Requires the backend stack:

```bash
docker compose up -d --wait backend
bunx playwright test           # or: npx playwright test
bunx playwright test --ui      # interactive mode
docker compose down -v         # teardown + wipe test data
```

Covers login/signup/reset flows, per-page data validation (`validation.spec.ts`), the customer portal, admin/user settings, and the EDA page (`eda.spec.ts` — asserts the page renders either live data or the not-provisioned empty states, never a crash).
