# Secret management (Vault) — scaffold

Secrets are kept out of source (spec §11). For production, source the backend
`.env` values from Vault (or a cloud secret manager) and inject as Kubernetes
secrets at deploy time (e.g. External Secrets Operator / Vault Agent Injector).

Managed secrets: `SECRET_KEY`, `POSTGRES_PASSWORD`, `ANTHROPIC_API_KEY`,
`FIIX_API_KEY`, `SMTP_PASSWORD`, `GRAFANA_PASSWORD`, `FIRST_SUPERUSER_PASSWORD`.

Read-only machine-data ingestion and human-approval gates for work orders and
machine-config changes are enforced in the API layer, not via secrets.
