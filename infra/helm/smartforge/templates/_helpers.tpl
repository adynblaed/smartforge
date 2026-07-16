{{/* Expand the name of the chart. */}}
{{- define "smartforge.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name (standard fullname helper).
Truncated at 63 chars because some Kubernetes name fields are limited to this.
*/}}
{{- define "smartforge.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Chart name and version for the helm.sh/chart label. */}}
{{- define "smartforge.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Common labels (app.kubernetes.io standard set). */}}
{{- define "smartforge.labels" -}}
helm.sh/chart: {{ include "smartforge.chart" . }}
{{ include "smartforge.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: smartforge
{{- end -}}

{{/* Selector labels (stable across upgrades — never add mutable labels here). */}}
{{- define "smartforge.selectorLabels" -}}
app.kubernetes.io/name: {{ include "smartforge.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* ServiceAccount name. */}}
{{- define "smartforge.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "smartforge.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* Images. */}}
{{- define "smartforge.backendImage" -}}
{{- printf "%s:%s" .Values.image.backend.repository (default .Chart.AppVersion .Values.image.backend.tag) -}}
{{- end -}}

{{- define "smartforge.frontendImage" -}}
{{- printf "%s:%s" .Values.image.frontend.repository (default .Chart.AppVersion .Values.image.frontend.tag) -}}
{{- end -}}

{{/* ------------------------------------------------------------------------
Secret names — one existingSecret per domain; falls back to the chart-rendered
dev Secret (see templates/secrets.yaml, gated by secrets.allowInlineDev).
------------------------------------------------------------------------- */}}
{{- define "smartforge.appSecretName" -}}
{{- default (printf "%s-app" (include "smartforge.fullname" .)) .Values.secrets.app.existingSecret -}}
{{- end -}}

{{- define "smartforge.postgresSecretName" -}}
{{- default (printf "%s-postgres" (include "smartforge.fullname" .)) .Values.postgres.existingSecret -}}
{{- end -}}

{{- define "smartforge.warehouseSecretName" -}}
{{- default (printf "%s-warehouse" (include "smartforge.fullname" .)) .Values.warehouse.existingSecret -}}
{{- end -}}

{{- define "smartforge.oracleSecretName" -}}
{{- default (printf "%s-oracle" (include "smartforge.fullname" .)) .Values.oracle.existingSecret -}}
{{- end -}}

{{- define "smartforge.anthropicSecretName" -}}
{{- default (printf "%s-anthropic" (include "smartforge.fullname" .)) .Values.secrets.anthropic.existingSecret -}}
{{- end -}}

{{/* Lake PVC name. */}}
{{- define "smartforge.lakeClaimName" -}}
{{- default (printf "%s-lake" (include "smartforge.fullname" .)) .Values.lake.storage.existingClaim -}}
{{- end -}}

{{/* Ingress hosts. */}}
{{- define "smartforge.apiHost" -}}
{{- default (printf "api.%s" .Values.domain) .Values.ingress.apiHost -}}
{{- end -}}

{{- define "smartforge.dashboardHost" -}}
{{- default (printf "dashboard.%s" .Values.domain) .Values.ingress.dashboardHost -}}
{{- end -}}

{{/* In-cluster endpoints (or external overrides). */}}
{{- define "smartforge.redisHost" -}}
{{- if .Values.redis.enabled -}}
{{- printf "%s-redis" (include "smartforge.fullname" .) -}}
{{- else -}}
{{- required "redis.externalHost is required when redis.enabled=false" .Values.redis.externalHost -}}
{{- end -}}
{{- end -}}

{{- define "smartforge.qdrantUrl" -}}
{{- if .Values.qdrant.enabled -}}
{{- printf "http://%s-qdrant:6333" (include "smartforge.fullname" .) -}}
{{- else -}}
{{- required "qdrant.externalUrl is required when qdrant.enabled=false" .Values.qdrant.externalUrl -}}
{{- end -}}
{{- end -}}

{{/* ------------------------------------------------------------------------
Shared non-secret environment (single source of truth). Rendered into two
ConfigMaps: the release ConfigMap (configmap.yaml) and the pre-install hook
copy (prestart-job.yaml) that exists before any release resource does.
------------------------------------------------------------------------- */}}
{{- define "smartforge.configData" -}}
DOMAIN: {{ .Values.domain | quote }}
ENVIRONMENT: {{ .Values.environment | quote }}
PROJECT_NAME: {{ .Values.config.projectName | quote }}
FRONTEND_HOST: {{ default (printf "https://%s" (include "smartforge.dashboardHost" .)) .Values.config.frontendHost | quote }}
BACKEND_CORS_ORIGINS: {{ default (printf "https://%s" (include "smartforge.dashboardHost" .)) .Values.config.corsOrigins | quote }}
FIRST_SUPERUSER: {{ .Values.config.firstSuperuser | quote }}
EMAILS_FROM_EMAIL: {{ .Values.config.emailsFromEmail | quote }}
SMTP_HOST: {{ .Values.config.smtp.host | quote }}
SMTP_USER: {{ .Values.config.smtp.user | quote }}
SMTP_PORT: {{ .Values.config.smtp.port | quote }}
SMTP_TLS: {{ .Values.config.smtp.tls | quote }}
SMTP_SSL: {{ .Values.config.smtp.ssl | quote }}
SENTRY_DSN: {{ .Values.config.sentryDsn | quote }}
POSTGRES_SERVER: {{ required "postgres.host is required (managed Postgres endpoint)" .Values.postgres.host | quote }}
POSTGRES_PORT: {{ .Values.postgres.port | quote }}
POSTGRES_DB: {{ .Values.postgres.db | quote }}
POSTGRES_USER: {{ .Values.postgres.user | quote }}
REDIS_HOST: {{ include "smartforge.redisHost" . | quote }}
REDIS_PORT: {{ (.Values.redis.enabled | ternary "6379" .Values.redis.externalPort) | quote }}
# The dedicated worker Deployment runs the simulator; never in the API pods.
SIMULATOR_ENABLED: "false"
SIMULATOR_INTERVAL_SECONDS: {{ .Values.config.simulatorIntervalSeconds | quote }}
ANTHROPIC_MODEL: {{ .Values.config.anthropicModel | quote }}
FIIX_BASE_URL: {{ .Values.config.fiixBaseUrl | quote }}
QDRANT_URL: {{ include "smartforge.qdrantUrl" . | quote }}
WAREHOUSE_DB: {{ .Values.warehouse.db | quote }}
WAREHOUSE_LOADER_USER: {{ .Values.warehouse.loaderUser | quote }}
WAREHOUSE_DBT_USER: {{ .Values.warehouse.dbtUser | quote }}
WAREHOUSE_API_USER: {{ .Values.warehouse.apiUser | quote }}
OMEGA_ORACLE_USER: {{ .Values.oracle.user | quote }}
OMEGA_ORACLE_HOST: {{ .Values.oracle.host | quote }}
OMEGA_ORACLE_PORT: {{ .Values.oracle.port | quote }}
OMEGA_ORACLE_SERVICE_NAME: {{ .Values.oracle.serviceName | quote }}
OMEGA_ORACLE_SID: {{ .Values.oracle.sid | quote }}
OMEGA_ORACLE_SCHEMAS: {{ .Values.oracle.schemas | quote }}
OMEGA_ORACLE_TLS_ENABLED: {{ .Values.oracle.tlsEnabled | quote }}
OMEGA_ORACLE_POOL_MIN: {{ .Values.oracle.poolMin | quote }}
OMEGA_ORACLE_POOL_MAX: {{ .Values.oracle.poolMax | quote }}
OMEGA_ORACLE_CALL_TIMEOUT_SECONDS: {{ .Values.oracle.callTimeoutSeconds | quote }}
OMEGA_ORACLE_FETCH_ARRAYSIZE: {{ .Values.oracle.fetchArraysize | quote }}
# Paths on the shared lake volume (see lake.storage in values.yaml).
LAKE_ROOT: "/srv/data/lake"
DUCKDB_PATH: "/srv/data/catalog/smartforge_lake.duckdb"
DUCKDB_MEMORY_LIMIT: {{ .Values.platform.duckdb.memoryLimit | quote }}
DUCKDB_THREADS: {{ .Values.platform.duckdb.threads | quote }}
PARQUET_COMPRESSION: {{ .Values.platform.parquetCompression | quote }}
LAKE_RETAINED_SNAPSHOTS: {{ .Values.platform.retainedSnapshots | quote }}
PLATFORM_ENV: {{ .Values.platform.env | quote }}
SEED_REQUIRE_CONFIRMATION: {{ .Values.platform.seedRequireConfirmation | quote }}
FRESHNESS_HOURLY_WARN_MINUTES: {{ .Values.platform.freshness.hourlyWarnMinutes | quote }}
FRESHNESS_HOURLY_ERROR_MINUTES: {{ .Values.platform.freshness.hourlyErrorMinutes | quote }}
FRESHNESS_DAILY_WARN_MINUTES: {{ .Values.platform.freshness.dailyWarnMinutes | quote }}
FRESHNESS_DAILY_ERROR_MINUTES: {{ .Values.platform.freshness.dailyErrorMinutes | quote }}
{{- range $k, $v := .Values.config.extra }}
{{ $k }}: {{ $v | quote }}
{{- end }}
{{- end -}}

{{/* ------------------------------------------------------------------------
Secret-backed env fragments (shared across backend / workers / prestart).
------------------------------------------------------------------------- */}}

{{/* Core app secrets — required by every backend-image workload. */}}
{{- define "smartforge.appSecretEnv" -}}
- name: SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "smartforge.appSecretName" . }}
      key: SECRET_KEY
- name: FIRST_SUPERUSER_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "smartforge.appSecretName" . }}
      key: FIRST_SUPERUSER_PASSWORD
- name: SMTP_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "smartforge.appSecretName" . }}
      key: SMTP_PASSWORD
      optional: true
{{- end -}}

{{- define "smartforge.postgresSecretEnv" -}}
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "smartforge.postgresSecretName" . }}
      key: POSTGRES_PASSWORD
{{- end -}}

{{/* ------------------------------------------------------------------------
Lake co-scheduling: with a ReadWriteOnce lake PVC the volume can only attach
to one node, so every pod that mounts it (backend + platform-worker) carries
the lake-attached label and requires affinity to that label. The first pod
scheduled matches its own selector (Kubernetes special case), so the group
bootstraps; all subsequent pods land on the same node. Not rendered for
ReadWriteMany.
------------------------------------------------------------------------- */}}
{{- define "smartforge.lakeAffinity" -}}
{{- if eq .Values.lake.storage.accessMode "ReadWriteOnce" }}
affinity:
  podAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels:
            smartforge.futureform.com/lake-attached: "true"
            app.kubernetes.io/instance: {{ .Release.Name }}
        topologyKey: kubernetes.io/hostname
{{- end }}
{{- end -}}

{{/* Pod securityContext for the Python (backend-image) workloads. The image
runs fine as an arbitrary non-root uid: the venv is world-readable and all
writes go to volumes (/srv/data) or /tmp. */}}
{{- define "smartforge.pythonPodSecurityContext" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault
{{- end -}}

{{- define "smartforge.pythonContainerSecurityContext" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: ["ALL"]
{{- end -}}
