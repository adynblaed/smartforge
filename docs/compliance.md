# Compliance — GDPR & SOC 2 Control Mapping (v1.0.0)

How SmartForge's implemented controls map to the GDPR and the SOC 2 Trust
Services Criteria. **Posture statement:** the platform *implements and
evidences* the technical controls below; formal certification (a SOC 2
Type I/II report, DPAs, appointing a DPO where required) is an
organizational action tracked with the executive sponsor — this document
never claims a certification that has not been audited.

Companion records: [`docs/data-platform.md`](data-platform.md)
(governance, owners, retention, exceptions),
[`specs/CHECKLIST.md`](../specs/CHECKLIST.md)
(GOV/IAM/SEC families), [`runbooks/`](../runbooks/).

## 1. Personal-data inventory (GDPR Art. 30 record basis)

| Data | Where | Classification | Lifecycle |
|---|---|---|---|
| Staff accounts: name, email, hashed password (Argon2) | app DB `users` | internal | Admin CRUD; deletable via `/admin`; audit-logged |
| Customer portal accounts + `customer_id` binding | app DB `users`, `customer` | confidential | Tenant-isolated at every query; deletable |
| Customer company contacts (name, contact email) | app DB + replicated `OMEGA.CUSTOMERS` → lake/warehouse | confidential (contract-tagged) | Source-driven; deletions propagate via delete reconciliation (`_is_deleted`), filtered from marts |
| Operational/audit trails (who did what) | `audit_logs`, `control.*`, `audit.*` | internal | Retained per OBS-012; identifiers only, never payloads |
| Backups of the above | `app-db-backups` volume | confidential | Rotate per `BACKUP_KEEP_*` (aged-out data leaves backups automatically) |

No special-category (Art. 9) data is in approved scope; the replication
contracts (`config/tables.yml`) are the enforcement point — uncontracted
data cannot enter the platform (DCT-001 fail-closed).

## 2. GDPR principle & rights mapping

| GDPR | Control implemented | Evidence |
|---|---|---|
| Art. 5(1)(c) minimization | Only contracted tables/columns extracted; unsupported/sensitive types excluded fail-closed | `config/tables.yml`, `type_mappings.yml` (GOV-003) |
| Art. 5(1)(e) storage limitation | Lake snapshot pruning, backup rotation, audit retention policy | dispatcher lake maintenance; `BACKUP_KEEP_*` (GOV-004) |
| Art. 15 access | User self-view (`/users/me`), admin lookup, datasource views | app routes + audit trail |
| Art. 16 rectification | User/admin CRUD; source-of-record corrections flow through replication | `/admin`, hourly sync |
| Art. 17 erasure | App: user deletion. Analytics: source deletion propagates via key reconciliation soft-marks; marts filter `_is_deleted`; backups age out on rotation | `reconcile_deletes.py` (GOV-011); procedure §4 below |
| Art. 20 portability | Authenticated CSV export of app data | `/datasources/export` |
| Art. 25 by design/default | Least-privilege identities, read-only source, RBAC, fail-closed contracts, immutable audit | CLAUDE.md §4, checklist IAM/SEC |
| Art. 32 security of processing | TLS at ingress, column-level encryption (`EncryptedString`), Argon2 hashing, role separation, secret scanning, rate limiting | `core/crypto.py`, `security-scan.yml`, compose middlewares |
| Art. 33/34 breach response | Sev-1 "data exposure" classification with immediate-response path | `runbooks/operations.md` §Incident severity |

## 3. SOC 2 Trust Services Criteria mapping

| Criteria | Control implemented | Evidence |
|---|---|---|
| CC1/CC2 (governance, communication) | Named owners, escalation routes, handbook, review cadence | `docs/data-platform.md` §1, §12 |
| CC3 (risk assessment) | Maintained risk register with owners/mitigations | `docs/data-platform.md` §5 |
| CC5/CC6 (logical access) | RBAC tiers (superuser/internal/customer), least-privilege DB roles, JWT auth, full-surface anonymous-rejection test, access recertification schedule | `deps.py`, `test_route_wiring.py`, IAM-015 |
| CC7 (system operations) | Health/readiness probes, freshness dead-man's switch, structured logging with correlation IDs, incident runbooks, alerting thresholds | `logging_config.py`, `/platform/freshness`, runbooks |
| CC8 (change management) | PR review + CI gates (tests, types, security scans), versioned migrations, GitOps deploys | `.github/workflows/`, Argo CD |
| A1 (availability) | Scheduled backups + automated restore drill, SLOs, capacity bounds, PDBs/HPA in Helm | `db-backup`, `scripts/restore-drill.sh`, §8 handbook |
| PI1 (processing integrity) | Idempotent loads, watermark-commit-last, SCN regression guard, row-count + control-total reconciliation, drift fail-closed, dbt test gates | `tests_dataplatform` (300+ proofs) |
| C1 (confidentiality) | Classification per contract, column encryption, secret hygiene (gitleaks), no payloads in logs | `tables.yml`, OBS-006 |
| P-series (privacy) | §1–§2 of this document (minimization, purpose limitation, rights procedures) | `docs/data-platform.md` §2, §6–7 |

## 4. Data-subject request procedures (operational)

1. **Access/portability:** authenticate the subject → app data via
   `/users/me` / admin lookup + `/datasources/export`; analytics footprint
   via `SELECT ... FROM raw_oracle.customers WHERE customer_id = :id`
   (read-only role) — return within the statutory window.
2. **Erasure:** delete/anonymize in the **source of record** (omega) →
   the next key reconciliation soft-marks the analytics rows
   (`_is_deleted=true`, filtered from all marts/api products) → published
   Parquet containing the historical rows ages out with snapshot pruning;
   backups age out per `BACKUP_KEEP_*`. For an immediate hard purge
   (legal demand): reseed the affected table at a new SCN
   (`runbooks/backfill.md`) — the new publication contains no trace, and
   retention removes prior snapshots. Record the request and completion in
   `audit_logs`.
3. **Restriction/objection:** pause the affected contract
   (`enabled: false`) pending resolution — data stops flowing without
   destroying state.

## 5. Organizational actions (not claimable in-repo)

Tracked with the sponsor alongside exceptions E1–E7: external SOC 2 audit
engagement, DPAs with processors (hosting, email), breach-notification
contact chain, DPO designation where required, and privacy-policy legal
review (`/privacy` page is a template, not counsel-reviewed).
