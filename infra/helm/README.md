# SmartForge Helm Chart (scaffold)

Kubernetes-ready direction (spec §10). Each compose service maps to a
Deployment + Service: `backend`, `worker`, `frontend`, `postgres` (or managed),
`redis`, `prometheus`, `grafana`.

Suggested layout:

```
helm/smartforge/
  Chart.yaml
  values.yaml          # image tags, replicas, resources, ingress hosts
  templates/
    backend-deployment.yaml
    worker-deployment.yaml
    frontend-deployment.yaml
    redis.yaml
    configmap-env.yaml
    secret-env.yaml     # sourced from Vault (see ../vault)
    ingress.yaml
    servicemonitor.yaml # Prometheus Operator scrape of /api/v1/metrics
```

Stateless API + worker scale horizontally; telemetry/order fan-out goes through
Redis pub/sub so multiple API replicas serve the same WebSocket stream.
