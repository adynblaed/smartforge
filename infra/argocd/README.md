# SmartForge — Argo CD GitOps

Argo CD deploys the Helm chart at [`../helm/smartforge`](../helm/smartforge).
Git is the single source of truth: nothing is deployed that is not committed.

| File | Purpose |
|------|---------|
| `appproject.yaml` | AppProject `smartforge` — restricts source repo and destination namespaces |
| `application-staging.yaml` | `smartforge-staging` ns, `values.yaml` + `values-staging.yaml`, automated sync with prune + selfHeal |
| `application-production.yaml` | `smartforge-production` ns, `values.yaml` + `values-production.yaml`, `automated: {prune: false, selfHeal: false}` — apply-only; see the manifest comment for a fully manual gate |

## Bootstrap

Prerequisites: Argo CD installed in `argocd`; the per-domain Secrets from
`../helm/README.md` provisioned in each target namespace (Argo CD does not
manage secret material); repo credentials configured if the repo is private
(`argocd repo add https://github.com/futureform/smartforge.git ...`).

```bash
kubectl apply -n argocd -f appproject.yaml
kubectl apply -n argocd -f application-staging.yaml
kubectl apply -n argocd -f application-production.yaml

argocd app list
argocd app sync smartforge-staging   # first sync, if not already triggered
```

(Equivalent `argocd app create --project smartforge ...` commands work too;
the declarative manifests above are the source-controlled path.)

Database migrations need no special handling: the chart's prestart Job carries
Helm `pre-install`/`pre-upgrade` hook annotations, which Argo CD runs as a
PreSync hook — a failed migration fails the sync before any pod rolls.

## Image update flow (CI -> PR -> merge -> sync)

1. A GitHub release triggers the build workflow (see `.github/workflows/`,
   e.g. `deploy-production.yml` for the current compose-based flow): CI builds
   `backend` and `frontend` images from the repo root Dockerfiles, tags them
   with the release semver (`v1.1.0`), and pushes to the registry. Remember:
   the frontend image bakes `VITE_API_URL` at build time — one image per
   environment.
2. CI (or a human) opens a PR bumping `image.backend.tag` /
   `image.frontend.tag` in `infra/helm/smartforge/values-staging.yaml`.
3. Merge -> Argo CD syncs staging automatically. Verify.
4. Promote by PR-ing the same bump into `values-production.yaml`; on merge the
   production app applies it (or run `argocd app sync smartforge-production`
   if you removed the `automated` block).

CI never talks to the cluster — it only pushes images and commits values.

## Rollback

Git-first, matching the GitOps model:

```bash
git revert <bad-values-commit>   # restore the previous image tag / values
git push
argocd app sync smartforge-production
```

`argocd app rollback smartforge-production <ID>` exists for emergencies, but
it leaves git ahead of the cluster (and selfHeal/auto-sync would re-apply git)
— always follow up with the revert commit. Schema note: rolling back the image
does not downgrade the database; alembic migrations must stay
backward-compatible one release back.

## Day-2 tips

- `argocd app diff smartforge-production` before syncing production.
- `ignoreDifferences` on `Deployment /spec/replicas` keeps the backend HPA
  from showing as permanent drift.
- Orphaned-resource warnings are enabled on the project: anything left behind
  by a chart refactor shows up in the UI instead of lingering silently.
