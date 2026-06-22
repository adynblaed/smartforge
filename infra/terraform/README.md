# SmartForge Terraform (scaffold)

Infrastructure-as-code direction (spec §10). Modules:

- `network/` — VPC, subnets, security groups
- `cluster/` — managed Kubernetes (EKS/GKE/AKS)
- `database/` — managed Postgres (multi-AZ), per-factory schemas/tenancy
- `cache/` — managed Redis
- `observability/` — managed Prometheus/Grafana or self-hosted via Helm
- `secrets/` — Vault (or cloud secret manager) for app secrets

Environment-based configuration via `terraform workspace` per site, supporting
multi-factory / multi-region expansion (spec §12).
