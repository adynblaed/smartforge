# SmartForge Helm Chart

Production deployment of SmartForge v1.0.0 on Kubernetes. Architecture,
invariants, and the failure-handling catalogue behind these choices:
[`../../specs/ARCHITECTURE.md`](../../specs/ARCHITECTURE.md) (§10
environments & deployment). The chart at [`smartforge/`](./smartforge)
maps the compose stack 1:1 onto Kubernetes primitives:

| Compose service   | Kubernetes resource                              | Notes |
|-------------------|--------------------------------------------------|-------|
| `backend`         | Deployment + Service + Ingress (+ optional HPA)  | FastAPI :8000, probes on `/api/v1/utils/health-check/` |
| `frontend`        | Deployment + Service + Ingress                   | nginx :80 serving the compiled dashboard |
| `prestart`        | Helm hook Job (`pre-install`,`pre-upgrade`)      | `bash scripts/prestart.sh` — wait-for-DB, alembic, seed |
| `worker`          | Deployment, **replicas: 1**, `Recreate`          | telemetry simulator — single producer, never scale |
| `platform-worker` | Deployment, **replicas: 1**, `Recreate`          | lake/DuckDB single writer, shares `/srv/data` PVC with backend |
| `redis`           | Minimal StatefulSet + PVC (or managed)           | prefer managed/Bitnami in production (`redis.enabled=false`) |
| `qdrant`          | StatefulSet + PVC                                | pinned image tag |
| `db` / warehouse  | **Not deployed** — managed Postgres              | see below |
| `prometheus`/`grafana` | **Not deployed** — use kube-prometheus-stack | `monitoring.serviceMonitor.enabled` scrapes `/api/v1/metrics` |
| adminer           | intentionally dropped in Kubernetes              | use `kubectl port-forward` / psql instead |

## Prerequisites

- Kubernetes >= 1.27, Helm 3 (chart `apiVersion: v2`)
- An ingress controller (ingress-nginx assumed; `ingress.className` configurable)
- cert-manager for TLS (set `ingress.annotations` cluster-issuer)
- **Managed PostgreSQL** (RDS / Cloud SQL / CloudNativePG operator). The chart
  never templates a database. Two logical databases are expected on it:
  - `app` (API + migrations) — `postgres.*` values
  - `warehouse` with role-separated identities (`warehouse_loader`,
    `warehouse_transformer`, `warehouse_api_reader`) — `warehouse.*` values
- Optional: Prometheus Operator (kube-prometheus-stack) for the ServiceMonitor
- Optional: an RWX StorageClass (EFS/Filestore/CephFS/NFS) for the lake volume

## Install / upgrade / rollback

```bash
kubectl create namespace smartforge

# provision secrets first (below), then:
helm install smartforge ./smartforge -n smartforge \
  -f smartforge/values.yaml -f smartforge/values-production.yaml

helm upgrade smartforge ./smartforge -n smartforge \
  -f smartforge/values.yaml -f smartforge/values-production.yaml

helm history smartforge -n smartforge
helm rollback smartforge <REVISION> -n smartforge
```

Migrations run automatically as a `pre-install`/`pre-upgrade` hook Job
(`bash scripts/prestart.sh`); the upgrade only proceeds when it succeeds. Note
that a `helm rollback` re-runs the hook but does **not** downgrade the schema —
alembic migrations must stay backward-compatible one release back.

## Secrets — the chart never renders production secret material

One existing Secret per domain, referenced by name from values. Exact key
contract consumed by the chart:

| Values key                        | Secret keys |
|-----------------------------------|-------------|
| `secrets.app.existingSecret`      | `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD`, `SANDBOX_USER_PASSWORD`, `SMTP_PASSWORD`?, `FIIX_API_KEY`?, `QDRANT_API_KEY`?, `METRICS_BEARER_TOKEN`? |
| `postgres.existingSecret`         | `POSTGRES_PASSWORD` |
| `warehouse.existingSecret`        | `WAREHOUSE_LOADER_PASSWORD`, `WAREHOUSE_DBT_PASSWORD`, `WAREHOUSE_API_PASSWORD` |
| `oracle.existingSecret`           | `OMEGA_ORACLE_PASSWORD` |
| `secrets.anthropic.existingSecret`| `ANTHROPIC_API_KEY`? (empty = deterministic offline AskAI fallback) |

Keys marked `?` are optional (`secretKeyRef.optional: true`).

```bash
kubectl -n smartforge create secret generic smartforge-app \
  --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=FIRST_SUPERUSER_PASSWORD='...' \
  --from-literal=SANDBOX_USER_PASSWORD='...' \
  --from-literal=SMTP_PASSWORD='...' \
  --from-literal=FIIX_API_KEY='...'
kubectl -n smartforge create secret generic smartforge-postgres \
  --from-literal=POSTGRES_PASSWORD='...'
kubectl -n smartforge create secret generic smartforge-warehouse \
  --from-literal=WAREHOUSE_LOADER_PASSWORD='...' \
  --from-literal=WAREHOUSE_DBT_PASSWORD='...' \
  --from-literal=WAREHOUSE_API_PASSWORD='...'
kubectl -n smartforge create secret generic smartforge-oracle \
  --from-literal=OMEGA_ORACLE_PASSWORD='...'
kubectl -n smartforge create secret generic smartforge-anthropic \
  --from-literal=ANTHROPIC_API_KEY='...'
```

Preferred production path: sync these Secrets from Vault or a cloud secret
manager via External Secrets Operator or the Vault Agent Injector (see
[`../vault/`](../vault) for the managed-secret inventory) — same names, same
keys, no change to the chart.

For throwaway dev clusters only, `secrets.allowInlineDev: true` (the
`values.yaml` default) lets the chart render Secrets from per-domain `inline:`
maps. The staging/production overlays set `allowInlineDev: false`, which makes
`helm template` fail fast if any `existingSecret` name is missing.

## Single-writer invariants (do not scale)

- **`worker`** (telemetry simulator): exactly one producer. Two replicas
  double-write telemetry/orders. `replicas: 1` is hardcoded — there is no
  values knob — and `strategy: Recreate` prevents old/new overlap on upgrade.
- **`platform-worker`** (data-platform scheduler): sole writer of the Parquet
  lake and DuckDB catalog under `/srv/data` (DuckDB is single-writer; a
  Postgres advisory lock enforces single-flight). Same hardcoded
  `replicas: 1` + `Recreate`.

## Lake storage (`/srv/data`)

`platform-worker` (writer) and `backend` (reader) share one PVC
(`lake.storage.*`):

- `accessMode: ReadWriteOnce` (default) — the volume attaches to one node, so
  the chart adds required podAffinity that co-schedules backend and
  platform-worker onto that node. Fine for staging/small clusters.
- `accessMode: ReadWriteMany` (production overlay) — requires an RWX
  StorageClass; removes the co-scheduling constraint. The single-writer
  invariant is unaffected.

Take periodic snapshots/backups of this volume; the lake retains
`LAKE_RETAINED_SNAPSHOTS` internal snapshots but that is not a backup.

## Building and pushing images

Build from the **repo root** (both Dockerfiles expect the root context), tag
with the semver release:

```bash
docker build -f backend/Dockerfile -t ghcr.io/futureform/smartforge-backend:v1.0.0 .
docker build -f frontend/Dockerfile \
  --build-arg VITE_API_URL=https://api.smartforge.futureform.com \
  --build-arg NODE_ENV=production \
  -t ghcr.io/futureform/smartforge-frontend:v1.0.0 .
docker push ghcr.io/futureform/smartforge-backend:v1.0.0
docker push ghcr.io/futureform/smartforge-frontend:v1.0.0
```

`VITE_API_URL` is baked into the frontend bundle at build time — build one
frontend image **per environment** (staging images use the staging API host).
Set the tags in the env overlay (`image.backend.tag`, `image.frontend.tag`);
an empty tag falls back to `Chart.appVersion`.

## GitOps / Argo CD

[`../argocd/`](../argocd) contains an AppProject plus one Application per
environment, both pointing at `infra/helm/smartforge` with the matching
`valueFiles`. Argo CD translates the prestart hook annotations to a PreSync
hook, so migrations run before each sync's rollout — identical ordering to
plain Helm. Deploys happen by merging a values PR (image tag bump); see
`../argocd/README.md` for bootstrap, image-update and rollback flows.

## Validation

```bash
helm lint ./smartforge
helm template smartforge ./smartforge -f smartforge/values-production.yaml
```
