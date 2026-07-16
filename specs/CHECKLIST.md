# Warehouse_Lake_Checklist.md

## Oracle-to-PostgreSQL and DuckDB Production Readiness Checklist

**Purpose:** Formal end-to-end review and acceptance checklist for modernizing a legacy Oracle Database and Oracle APEX application into a secure, role-based, observable, and scalable business intelligence and analytics platform using:

- Oracle Database as the read-only system of record
- `python-oracledb` and SQLAlchemy for source connectivity
- PyArrow and Parquet for canonical raw analytical storage
- PostgreSQL as the analytical data warehouse
- DuckDB as the lake query engine
- dlt for extraction, state, and loading workflows
- dbt for transformation, testing, lineage, and documentation
- FastAPI for governed analytical access
- External orchestration for hourly, daily, and reconciliation schedules

---

# 1. How to Use This Checklist

Each line item must be reviewed and supported by evidence.

**Status values**

- `[ ]` Not reviewed
- `[~]` In progress or partially compliant
- `[x]` Accepted
- `[!]` Exception approved
- `[X]` Rejected or blocking

**Priority**

- **P0:** Production-blocking
- **P1:** Required for production readiness
- **P2:** Strongly recommended
- **P3:** Optimization or maturity enhancement

**Required evidence may include**

- Architecture diagrams
- SQL grants and role definitions
- Configuration files
- Test results
- Logs and dashboards
- Data-quality reports
- Runbooks
- Approval records
- Recovery test evidence
- Security review records
- Performance test reports
- Business-owner sign-off

A production release must not proceed while any unapproved **P0** item remains incomplete.

---

# 1a. v1.0.0 Review Record (2026-07-15)

| Field | Value |
|---|---|
| Release | **v1.0.0** (SmartForge LTS) |
| Review date | 2026-07-15 |
| Reviewed by | Data Platform Engineering, with sponsor sign-off (§27) |
| Result | **Approved with documented exceptions** — 20 items `[!]`, all others `[x]` |
| Exceptions register | [`docs/data-platform.md`](../docs/data-platform.md) §10 (E1–E7: owner, rationale, compensating control, re-review trigger) |
| Next formal review | 2027-01-15 or before the next major release, whichever is earlier |

**Evidence index** (where acceptance evidence lives, by item family):

| Family | Primary evidence |
|---|---|
| DOC | `docs/data-platform.md` (owners §1, scope §2, environments §3, decision log §4, risks §5, exceptions §10); this file is version-controlled |
| SRC | `config/tables.yml`, `config/type_mappings.yml`, `sql/oracle_inventory.sql`, discovery artifacts (written to `config/generated/` at `cli discover` time — runtime output, not tracked; persisted plans live in `control.seed_plans`), `backend/app/dataplatform/oracle/metadata.py` |
| ORA | `backend/app/dataplatform/oracle/connection.py` (`verify_read_only`, bounded pool/timeouts), `backend/tests_dataplatform/test_extractor_sql.py` (bind variables, keyset) |
| IAM / SEC | `sql/postgres_roles.sql`, `backend/app/dataplatform/warehouse/postgres.py` (role grants), Traefik middlewares (`compose.yml`), `.github/workflows/security-scan.yml`, `backend/tests_dataplatform/test_api_*.py` (401/403, superuser gates) |
| DCT / SEED / INC | `backend/app/dataplatform/pipeline/{plans,full_seed,incremental,state}.py`, `backend/tests_dataplatform/test_pipeline_ordering.py` (watermark-last across 12 injected failures), `test_seed_plans.py`, `test_registry_contracts.py` |
| LAKE / DDB | `backend/app/dataplatform/lake/{parquet,manifest,duckdb_catalog}.py`, `backend/tests_dataplatform/test_lake_parquet.py` (immutability), `test_duckdb_catalog.py` (read-only proof) |
| PG / DLT | `backend/app/dataplatform/warehouse/{postgres,loader}.py` (staged merge, SCN guard, bounded pools/timeouts), `compose.yml` `db-backup`, `runbooks/backup_restore.md` |
| DBT / IQ | `dbt/` (tests, source freshness, exposures, snapshots, contracts), CI dual-target parse + docs artifact (`.github/workflows/ci-pipeline.yml`) |
| API / BI | `backend/app/api/routes/{platform,warehouse,lake}.py`, `backend/tests_dataplatform/test_api_*.py`, `backend/tests_smartforge/test_route_wiring.py` (full-surface auth sweep), frontend `/data-platform` page |
| DQ / OBS | `backend/app/dataplatform/pipeline/{reconciliation,freshness}.py`, `control.*`/`audit.*` schemas, `dbt/tests/` |
| PERF / DR / OPS | resource bounds throughout; `runbooks/` (operations, backup_restore, backfill, rollback, schema_drift, incident_stale_data) |
| CICD | `.github/workflows/` (test-backend, ci-pipeline, playwright, security-scan, pre-commit, zizmor, deploys), pinned lockfiles |
| GOV / CUT | `docs/data-platform.md` §2, §6–§7, §10–§11; cutover items E7 pending real parallel-run |

---

# 2. Document Control and Accountability

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | DOC-001 | P0 | A named executive sponsor is assigned. | Sponsor, decision authority, and escalation route are recorded. |
| [x] | DOC-002 | P0 | A technical owner is assigned for the source, pipeline, warehouse, lake, API, and BI layers. | Each platform component has one accountable owner and at least one backup. |
| [x] | DOC-003 | P0 | The migration scope is formally approved. | Approved Oracle schemas, tables, views, APEX applications, reports, and excluded objects are documented. |
| [x] | DOC-004 | P0 | The system-of-record boundary is explicit. | Oracle is documented as authoritative until an approved cutover changes that designation. |
| [x] | DOC-005 | P0 | The platform purpose is documented. | The design clearly distinguishes analytical replication from transactional application replacement. |
| [x] | DOC-006 | P1 | Environments are defined. | Development, test, staging, and production boundaries, credentials, storage, and promotion paths are documented. |
| [x] | DOC-007 | P1 | Architecture diagrams are current. | Logical, physical, network, identity, data-flow, and trust-boundary diagrams match deployed reality. |
| [x] | DOC-008 | P1 | A decision log exists. | Major architectural choices, rejected alternatives, assumptions, and review dates are recorded. |
| [x] | DOC-009 | P1 | A risk register exists. | Security, data quality, source-load, operational, vendor, and migration risks have owners and mitigations. |
| [x] | DOC-010 | P1 | Exception management is defined. | Exceptions include owner, rationale, compensating control, expiration date, and approval authority. |
| [x] | DOC-011 | P2 | Glossary and naming standards exist. | Source, raw, stage, mart, lake, semantic, API, freshness, and lineage terms are used consistently. |
| [x] | DOC-012 | P2 | The checklist itself is version-controlled. | Review history, approvals, and release association are traceable in source control. |

---

# 3. Legacy Oracle and APEX Discovery

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | SRC-001 | P0 | Approved Oracle schemas are inventoried. | Schema owners, business owners, sensitivity classifications, and extraction eligibility are recorded. |
| [x] | SRC-002 | P0 | All candidate tables and views are inventoried. | Inventory includes row counts, sizes, columns, keys, partitions, dependencies, and refresh requirements. |
| [x] | SRC-003 | P0 | Primary keys are confirmed for every replicated table. | Missing, composite, mutable, or unreliable keys have an approved alternative strategy. |
| [x] | SRC-004 | P0 | Candidate incremental cursor columns are validated. | Evidence proves the cursor changes on every relevant insert or update and has sufficient precision. |
| [x] | SRC-005 | P0 | Delete behavior is documented per table. | Soft-delete, hard-delete, audit-log, full-replace, or reconciliation strategy is assigned. |
| [x] | SRC-006 | P0 | Oracle data types are inventoried. | NUMBER precision/scale, DATE, timestamps, LOBs, RAW, JSON, XML, spatial, object, and virtual columns are identified. |
| [x] | SRC-007 | P0 | APEX dependencies are mapped. | APEX pages, reports, computations, validations, REST sources, packages, views, and authorization schemes are linked to data objects. |
| [x] | SRC-008 | P0 | PL/SQL dependencies are documented. | Packages, functions, triggers, procedures, and jobs affecting extracted data are identified. |
| [!] | SRC-009 | P1 | Business-critical reports are baselined. | Current report definitions, parameters, outputs, row counts, and totals are captured for comparison. |
| [x] | SRC-010 | P1 | Source data ownership is confirmed. | Each table or domain has a business steward who can approve meaning and quality. |
| [x] | SRC-011 | P1 | Source timezone semantics are documented. | Database timezone, session timezone, local timestamps, UTC policy, and daylight-saving behavior are known. |
| [x] | SRC-012 | P1 | Empty-string and null semantics are documented. | Oracle empty-string behavior and target normalization policy are approved. |
| [x] | SRC-013 | P1 | Character sets and Unicode requirements are documented. | Source character set, national character set, and test cases for multilingual content are recorded. |
| [!] | SRC-014 | P1 | Source load constraints are agreed. | Approved extraction windows, maximum concurrent sessions, query duration, and resource limits are documented. |
| [!] | SRC-015 | P1 | Source statistics and execution plans are reviewed. | High-volume extraction queries are explain-planned and do not cause avoidable full scans or contention. |
| [x] | SRC-016 | P2 | Historical data retention is inventoried. | Source retention, archive tables, purging jobs, and business retention requirements are known. |
| [x] | SRC-017 | P2 | Data classification is assigned at column level. | Sensitive, confidential, regulated, internal, and public fields are tagged. |
| [x] | SRC-018 | P2 | Non-tabular APEX assets are scoped separately. | Static files, application exports, templates, shared components, and authentication configuration have a migration plan or explicit exclusion. |

---

# 4. Oracle Source Safety and Read-Only Access

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | ORA-001 | P0 | A dedicated extraction identity exists. | No person, application owner, or APEX runtime account is reused for analytics extraction. |
| [x] | ORA-002 | P0 | The extraction identity is read-only. | Grants show only session creation, approved metadata access, and SELECT/READ on approved objects. |
| [x] | ORA-003 | P0 | Write operations are proven to fail. | Negative tests confirm INSERT, UPDATE, DELETE, MERGE, DDL, and procedure execution are denied. |
| [x] | ORA-004 | P0 | Credentials are not embedded in code. | Secrets are injected through an approved secret store or protected runtime mechanism. |
| [!] | ORA-005 | P0 | Network access is restricted. | Only approved pipeline hosts or service identities can reach the Oracle listener. |
| [!] | ORA-006 | P0 | TLS or Oracle wallet requirements are implemented when required. | Connection encryption and certificate validation match the security architecture. |
| [x] | ORA-007 | P0 | Source sessions are bounded. | Pool size, connection timeout, statement timeout, and retry policy protect the transactional workload. |
| [x] | ORA-008 | P0 | Extraction uses bind variables. | User or configuration values are never interpolated into SQL text except trusted allowlisted identifiers. |
| [x] | ORA-009 | P1 | Query allowlists exist. | Only approved schemas, tables, columns, filters, and extraction templates can run in production. |
| [x] | ORA-010 | P1 | Source auditing is enabled or independently logged. | Connection identity, query template, table, start time, duration, SCN, and rows read are traceable. |
| [x] | ORA-011 | P1 | Flashback or read-only transaction prerequisites are verified. | Required privileges, undo retention, and operational limits are documented and tested. |
| [x] | ORA-012 | P1 | Oracle connection failover behavior is tested. | Lost sessions, listener restarts, network interruption, and expired credentials fail safely. |
| [x] | ORA-013 | P1 | Source query cancellation is supported. | Operators can terminate runaway extraction without restarting the platform. |
| [!] | ORA-014 | P1 | Source query resource consumption is monitored. | Database administrators can see extraction CPU, I/O, temp use, sessions, and waits. |
| [x] | ORA-015 | P2 | A controlled Oracle-native backup or Data Pump procedure exists where approved. | Data Pump is treated as a recovery or Oracle-to-Oracle artifact, not as the direct PostgreSQL/DuckDB load format. |
| [x] | ORA-016 | P2 | The source account is periodically reviewed. | Grants, password rotation, unused access, and approved object scope are recertified. |

---

# 5. Identity, RBAC, and Authorization

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | IAM-001 | P0 | Human and service identities are separated. | Loader, transformer, API, BI, operator, developer, and administrator identities are distinct. |
| [x] | IAM-002 | P0 | Least privilege is implemented for every component. | Role grants show only the permissions required for assigned responsibilities. |
| [x] | IAM-003 | P0 | PostgreSQL roles are separated by function. | At minimum: loader, dbt transformer, API reader, BI reader, operator, and administrator. |
| [x] | IAM-004 | P0 | DuckDB and lake permissions separate writers from readers. | Only ingestion can publish or modify datasets; API and BI users are read-only. |
| [x] | IAM-005 | P0 | FastAPI authentication is implemented. | Anonymous access is disabled unless explicitly approved for a public dataset. |
| [x] | IAM-006 | P0 | FastAPI authorization is role- or attribute-based. | Endpoint, dataset, row, and column access are evaluated against verified claims. |
| [x] | IAM-007 | P0 | PostgreSQL row-level security is applied where required. | Policies are tested for permitted and denied identities, including bypass and owner behavior. |
| [x] | IAM-008 | P0 | Sensitive columns are protected. | Column grants, secure views, masking, tokenization, or omission prevent unauthorized disclosure. |
| [!] | IAM-009 | P0 | Administrative privileges require stronger controls. | MFA, just-in-time elevation, approval, short session duration, and audit logging are implemented where supported. |
| [x] | IAM-010 | P1 | Group-based access is preferred over direct user grants. | Users receive access through managed roles or identity-provider groups. |
| [x] | IAM-011 | P1 | Joiner, mover, and leaver processes are defined. | Access is granted, changed, and revoked within documented service levels. |
| [x] | IAM-012 | P1 | Service-account credential rotation is automated or scheduled. | Rotation can occur without code changes or prolonged outage. |
| [x] | IAM-013 | P1 | Authorization denial is tested. | Tests verify inaccessible datasets remain inaccessible through alternate endpoints, exports, joins, or metadata. |
| [x] | IAM-014 | P1 | Data-owner approval is required for sensitive access. | Access request records identify scope, duration, purpose, and approver. |
| [x] | IAM-015 | P1 | Access recertification is scheduled. | Privileged and sensitive-data access is reviewed at an approved interval. |
| [x] | IAM-016 | P1 | Break-glass access is controlled. | Emergency access is time-limited, logged, reviewed, and revoked after use. |
| [x] | IAM-017 | P2 | Separation of duties is enforced. | No single routine operator can both alter production data pipelines and approve the same change. |
| [x] | IAM-018 | P2 | Dataset entitlements are discoverable. | Catalog users can determine who owns a dataset and how to request access. |

---

# 6. Secrets, Cryptography, and Network Security

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | SEC-001 | P0 | All credentials are stored in an approved secrets system. | Source control, images, manifests, logs, notebooks, and environment examples contain no live secrets. |
| [x] | SEC-002 | P0 | Encryption in transit is enforced. | Oracle, PostgreSQL, API, object storage, and administrative connections use approved encryption. |
| [!] | SEC-003 | P0 | Encryption at rest is implemented. | Warehouse volumes, lake storage, backups, and secrets storage meet organizational requirements. |
| [x] | SEC-004 | P0 | Network trust zones are defined. | Source, ingestion, warehouse, lake, API, BI, and administrative paths are explicitly permitted or denied. |
| [x] | SEC-005 | P0 | The FastAPI service is not directly exposed without an approved ingress or proxy. | TLS termination, request limits, authentication, and security headers are enforced. |
| [x] | SEC-006 | P0 | Database ports are not broadly internet-accessible. | Firewall, security-group, and routing evidence confirms restricted access. |
| [x] | SEC-007 | P0 | Container and host images are hardened. | Unneeded packages, shells, users, and capabilities are removed or disabled. |
| [x] | SEC-008 | P0 | Dependency vulnerabilities are scanned. | Build pipelines fail on unapproved critical vulnerabilities. |
| [x] | SEC-009 | P1 | Secrets are redacted from logs and errors. | Automated tests verify DSNs, tokens, passwords, and authorization headers are not emitted. |
| [x] | SEC-010 | P1 | Certificate lifecycle is managed. | Issuance, renewal, revocation, expiry alerting, and trust stores are documented. |
| [x] | SEC-011 | P1 | Administrative interfaces are isolated. | Database administration, metrics, orchestration, and deployment endpoints require protected access. |
| [x] | SEC-012 | P1 | Rate limits and abuse controls are configured. | API clients cannot exhaust database pools, CPU, memory, or file handles. |
| [x] | SEC-013 | P1 | Security headers are verified. | Relevant response headers and browser-facing controls are tested at ingress. |
| [x] | SEC-014 | P1 | Supply-chain integrity is controlled. | Dependencies are pinned, artifacts are traceable, and builds are reproducible enough for incident analysis. |
| [!] | SEC-015 | P2 | Artifact signing or provenance is implemented. | Deployment images and release artifacts can be verified before promotion. |
| [x] | SEC-016 | P2 | Security testing is recurring. | Static analysis, dependency scanning, API testing, and periodic penetration testing are scheduled. |

---

# 7. Data Contracts and Schema Management

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | DCT-001 | P0 | Every table has a replication contract. | Contract includes owner, key, cursor, cadence, delete strategy, partitioning, classification, and destination name. |
| [x] | DCT-002 | P0 | Oracle-to-target type mappings are explicit. | No high-risk type relies on accidental driver inference. |
| [x] | DCT-003 | P0 | Numeric precision is preserved. | Financial and identifier fields are not silently converted to floating point. |
| [x] | DCT-004 | P0 | Time semantics are preserved. | DATE, TIMESTAMP, timezone-aware timestamp, UTC normalization, and display timezone policies are tested. |
| [x] | DCT-005 | P0 | LOB handling is defined. | CLOB, BLOB, XML, JSON, and oversized fields have size limits, streaming behavior, and destination policy. |
| [x] | DCT-006 | P0 | Primary-key and uniqueness guarantees are tested. | Duplicate and null-key conditions block publication unless explicitly approved. |
| [x] | DCT-007 | P0 | Schema drift is detected before target publication. | Ordered column metadata is fingerprinted and compared to the approved contract. |
| [x] | DCT-008 | P0 | Incompatible schema drift fails closed. | Type narrowing, scale changes, key changes, and removals pause the affected table. |
| [x] | DCT-009 | P1 | Compatible additive changes follow an approved process. | New nullable columns are reviewed, mapped, tested, and documented. |
| [x] | DCT-010 | P1 | Column renames are mapped explicitly. | Renames are not silently treated as unrelated data without owner approval. |
| [x] | DCT-011 | P1 | Raw-layer naming conventions are defined. | Source names, normalized names, reserved words, case handling, and collisions are deterministic. |
| [x] | DCT-012 | P1 | Metadata columns are standardized. | Source system, schema, table, SCN, load ID, extraction time, row hash, and deletion state are consistent. |
| [x] | DCT-013 | P1 | Contract changes are versioned. | Changes identify effective date, migration path, downstream impact, and rollback plan. |
| [x] | DCT-014 | P1 | Invalid records are quarantined. | Rejected rows retain reason, source key, load ID, and recoverable representation. |
| [x] | DCT-015 | P2 | Data dictionaries are published. | Definitions, owners, classifications, keys, freshness, and usage guidance are discoverable. |
| [x] | DCT-016 | P2 | Semantic definitions are version-controlled. | Metrics and dimensions have stable definitions and change history. |

---

# 8. Initial Snapshot and Full Seed

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | SEED-001 | P0 | One approved consistency strategy is selected. | Flashback SCN, one read-only transaction, or an approved weaker boundary is documented. |
| [x] | SEED-002 | P0 | The source SCN or transaction boundary is recorded. | All tables in the initial seed can be traced to the same approved source boundary. |
| [x] | SEED-003 | P0 | Undo-retention feasibility is confirmed. | The expected extraction duration fits the supported historical-read window. |
| [x] | SEED-004 | P0 | Large-table extraction uses deterministic pagination. | Keyset or partition-based pagination is used instead of unstable OFFSET paging. |
| [x] | SEED-005 | P0 | Extracts are written to unpublished staging paths. | Consumers cannot see partial datasets. |
| [x] | SEED-006 | P0 | Every seed produces a manifest. | Manifest includes source SCN, row count, files, schema hash, timing, and status. |
| [x] | SEED-007 | P0 | Seed publication is atomic or pointer-based. | Consumers transition from old to new data without reading an incomplete state. |
| [x] | SEED-008 | P0 | PostgreSQL seed loading is staged. | Production raw tables are swapped or promoted only after validation. |
| [x] | SEED-009 | P0 | The same Parquet seed feeds PostgreSQL and DuckDB. | Both destinations demonstrably represent the same source snapshot. |
| [x] | SEED-010 | P0 | Seed reconciliation is complete. | Counts, keys, ranges, nulls, critical totals, and samples agree within approved tolerances. |
| [x] | SEED-011 | P1 | Source load is measured during the seed. | CPU, I/O, session count, waits, temp use, and query duration stay within approved thresholds. |
| [x] | SEED-012 | P1 | Seed interruption and restart are tested. | A partial seed can resume or safely restart without corrupting published data. |
| [x] | SEED-013 | P1 | Seed files are immutable after publication. | Changes require a new load ID and new manifest. |
| [x] | SEED-014 | P1 | Optional Data Pump backup aligns with the seed boundary. | When used, the export SCN, logs, retention, and restore procedure are recorded. |
| [x] | SEED-015 | P1 | Rollback is defined. | Previous PostgreSQL tables, prior lake pointers, and dbt models can be restored. |
| [!] | SEED-016 | P2 | Seed duration is benchmarked. | Future reseed windows and capacity requirements are known. |

---

# 9. Incremental Replication and Synchronization

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | INC-001 | P0 | Every table has an approved incremental strategy. | Updated timestamp, monotonic key, full replace, key reconciliation, or bucket reconciliation is configured. |
| [x] | INC-002 | P0 | Each run captures a fixed upper boundary. | Incremental extraction does not chase an indefinitely moving present. |
| [x] | INC-003 | P0 | Lower-bound overlap is configured where required. | Timestamp precision, late visibility, and equal-cursor rows cannot create gaps. |
| [x] | INC-004 | P0 | Loads are idempotent. | Reprocessing the same load does not duplicate or regress destination records. |
| [x] | INC-005 | P0 | Watermarks advance only after successful publication. | Source state remains unchanged when extraction, loading, dbt, or validation fails. |
| [x] | INC-006 | P0 | Older loads cannot overwrite newer records. | Source SCN, version, or cursor ordering prevents state regression. |
| [x] | INC-007 | P0 | Hard-delete handling is implemented. | Missing source rows are detected through soft deletes, audit logs, reconciliation, full replacement, or CDC. |
| [x] | INC-008 | P0 | Composite cursor ties are deterministic. | Ordering includes cursor plus stable key and state persists enough information to resume safely. |
| [x] | INC-009 | P1 | Incremental state is stored transactionally. | Run state, manifest state, watermark, and publication status cannot diverge silently. |
| [x] | INC-010 | P1 | Late-arriving and backdated records are tested. | Approved overlap or reconciliation strategy captures records outside normal order. |
| [x] | INC-011 | P1 | Full-refresh fallback exists. | Operators can reseed one table without rebuilding the entire platform. |
| [x] | INC-012 | P1 | Table schedules are configurable. | Hourly, daily, weekly, disabled, and ad hoc modes are controlled through configuration. |
| [x] | INC-013 | P1 | Concurrent runs are controlled. | Locks or orchestration prevent overlapping loads for the same table or partition. |
| [x] | INC-014 | P1 | Retry behavior is bounded. | Transient retries use backoff and do not overload Oracle or create duplicate publications. |
| [x] | INC-015 | P1 | Incremental reconciliation is automated. | Source extract count, lake count, warehouse stage count, and merge result are compared. |
| [x] | INC-016 | P2 | Change-volume baselines are maintained. | Unexpected spikes or drops alert operators and data owners. |

---

# 10. Parquet Data Lake Readiness

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | LAKE-001 | P0 | The lake uses immutable published datasets. | Published Parquet files are never edited in place. |
| [x] | LAKE-002 | P0 | Staging, published, quarantine, and catalog areas are separated. | Consumers cannot query incomplete or rejected loads. |
| [x] | LAKE-003 | P0 | File paths are deterministic and versioned. | Schema, table, partition, load ID, and snapshot identifiers are encoded consistently. |
| [x] | LAKE-004 | P0 | Every published load has a manifest. | The manifest is authoritative for completeness, provenance, and reconciliation. |
| [x] | LAKE-005 | P0 | Partitioning matches query behavior. | Common date and domain filters eliminate files without producing excessive cardinality. |
| [x] | LAKE-006 | P0 | Small-file proliferation is controlled. | Compaction targets and thresholds are defined and monitored. |
| [x] | LAKE-007 | P0 | Schema evolution is controlled. | `union_by_name` or equivalent behavior is not used as a substitute for validation. |
| [x] | LAKE-008 | P0 | Sensitive datasets are physically and logically isolated. | Directory permissions and catalog exposure prevent unauthorized access. |
| [x] | LAKE-009 | P1 | Parquet compression is standardized. | Compression, row-group sizing, and file-size targets are benchmarked. |
| [x] | LAKE-010 | P1 | Statistics and metadata support pruning. | Files contain useful column statistics for common filters where supported. |
| [x] | LAKE-011 | P1 | Retention policy is implemented. | Raw snapshots, increments, manifests, quarantine, and temporary files have approved lifecycles. |
| [x] | LAKE-012 | P1 | Orphaned files are detected. | Files without manifests, manifests without files, and abandoned staging loads are reported. |
| [x] | LAKE-013 | P1 | Lake backups or replication match business requirements. | Recovery point, recovery time, and restore tests are documented. |
| [x] | LAKE-014 | P1 | File integrity is verifiable. | Checksums, object versions, or storage integrity controls can detect corruption. |
| [x] | LAKE-015 | P2 | Table-level data lineage is published. | Users can trace each lake dataset to Oracle object, SCN, load, transformation, and owner. |
| [x] | LAKE-016 | P2 | Cold and hot data tiers are defined. | Query performance and storage cost are balanced without breaking transparency. |

---

# 11. DuckDB Query Layer

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | DDB-001 | P0 | DuckDB is treated as an analytical engine, not a transactional service. | The design does not depend on unsupported multi-writer application behavior. |
| [x] | DDB-002 | P0 | Only one controlled process writes the DuckDB catalog. | API and BI processes open the database read-only. |
| [x] | DDB-003 | P0 | FastAPI connections use read-only mode. | Runtime tests prove API workers cannot modify catalog objects or datasets. |
| [x] | DDB-004 | P0 | DuckDB views point only to published paths. | No view references staging or quarantine directories. |
| [x] | DDB-005 | P0 | Query memory and thread limits are configured. | One analytical query cannot exhaust the host or starve other workloads. |
| [x] | DDB-006 | P0 | Query timeouts or cancellation controls exist. | Runaway scans can be interrupted and clients receive a bounded failure response. |
| [x] | DDB-007 | P1 | Catalog updates are atomic. | View refresh or pointer changes cannot leave a partially updated catalog. |
| [x] | DDB-008 | P1 | DuckDB version upgrades are tested against all models. | Compatibility, performance, extensions, and file behavior are validated before promotion. |
| [x] | DDB-009 | P1 | Parquet pushdown is verified for common queries. | Explain plans show expected column and filter pruning. |
| [x] | DDB-010 | P1 | Extension use is allowlisted. | Only approved extensions can be installed or loaded. |
| [x] | DDB-011 | P1 | Concurrency tests represent expected API load. | Read-only multi-process behavior and resource limits meet service objectives. |
| [x] | DDB-012 | P2 | Local cache behavior is documented. | Operators understand which files, metadata, and results may be cached. |
| [x] | DDB-013 | P2 | Query profiles are retained for slow-query analysis. | Operators can identify scan size, filters, joins, spills, and bottlenecks. |
| [x] | DDB-014 | P2 | Lake query templates are version-controlled. | Approved SQL and semantic models can be reviewed and reproduced. |

---

# 12. PostgreSQL Warehouse Readiness

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | PG-001 | P0 | Warehouse schemas are separated by responsibility. | At minimum: control, raw, staging, intermediate, marts, API, and audit. |
| [x] | PG-002 | P0 | The loader cannot modify curated schemas. | Grants prevent accidental writes outside raw, control, and approved audit areas. |
| [x] | PG-003 | P0 | The API role is read-only. | It can access only approved API views and marts. |
| [x] | PG-004 | P0 | Raw tables have stable keys or documented exceptions. | Merge logic, duplicates, and replacement behavior are deterministic. |
| [x] | PG-005 | P0 | Bulk loads use staged publication. | Consumers never read half-loaded replacement tables. |
| [x] | PG-006 | P0 | Merge logic is tested for insert, update, replay, and regression. | Older SCNs or versions cannot replace newer state. |
| [x] | PG-007 | P0 | Database connection limits and pools are coordinated. | Ingestion, dbt, API, BI, and administration cannot collectively exceed safe limits. |
| [x] | PG-008 | P0 | Query and transaction timeouts are configured. | Long-running API queries and forgotten transactions are terminated safely. |
| [x] | PG-009 | P0 | Backup and point-in-time recovery are configured. | Restore tests meet documented RPO and RTO. |
| [x] | PG-010 | P1 | Indexes are based on real query patterns. | Primary keys, joins, filters, and pagination paths are measured and justified. |
| [x] | PG-011 | P1 | Table statistics and vacuum behavior are healthy. | Autovacuum, analyze, bloat, dead tuples, and freeze risk are monitored. |
| [x] | PG-012 | P1 | Partitioning is used only when justified. | Partition keys, pruning, maintenance, and query behavior are validated. |
| [x] | PG-013 | P1 | Materialized views have controlled refresh behavior. | Refresh cadence, concurrency, invalidation, and failure handling are documented. |
| [x] | PG-014 | P1 | Row-level security policies are tested. | Positive, negative, owner, superuser, and alternate-path tests are recorded. |
| [x] | PG-015 | P1 | Warehouse schema changes are migration-controlled. | DDL is applied through versioned migrations with rollback or forward-fix plans. |
| [x] | PG-016 | P1 | Slow queries are observable. | Query fingerprints, execution plans, wait events, rows, and duration are available. |
| [x] | PG-017 | P1 | Resource saturation is monitored. | CPU, memory, storage, IOPS, locks, connections, replication, and cache ratios are visible. |
| [x] | PG-018 | P2 | Read replicas are evaluated for BI isolation. | Decision accounts for consistency, complexity, and service-level requirements. |
| [x] | PG-019 | P2 | Data lifecycle maintenance is automated. | Old staging tables, superseded snapshots, and unused indexes are removed safely. |
| [x] | PG-020 | P2 | Warehouse cost and growth forecasts exist. | Capacity plans include raw, marts, indexes, WAL, backups, and temporary space. |

---

# 13. dlt and Pipeline Framework Readiness

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | DLT-001 | P0 | Pipeline state storage is durable. | State survives restarts, redeployments, and worker replacement. |
| [x] | DLT-002 | P0 | Pipeline state cannot advance before target acceptance. | State commit is coordinated with manifest, load, and validation completion. |
| [x] | DLT-003 | P0 | Source and target schemas are explicitly controlled. | Automatic schema evolution cannot create unsafe production changes. |
| [x] | DLT-004 | P0 | Merge keys are correct and tested. | Inserts, updates, duplicate input, and replay produce expected state. |
| [x] | DLT-005 | P0 | Failed load packages are inspectable and replayable. | Operators can identify affected tables, rows, files, and error causes. |
| [x] | DLT-006 | P1 | dlt configuration and secrets are separated. | Non-secret table contracts are versioned; secrets remain external. |
| [x] | DLT-007 | P1 | Pipeline package versions are pinned. | Production behavior is reproducible across deployments. |
| [x] | DLT-008 | P1 | Custom normalizers and adapters are tested. | Type mapping, naming, null handling, and metadata fields have unit tests. |
| [x] | DLT-009 | P1 | Destination retries are idempotent. | Temporary PostgreSQL or storage failures do not duplicate data. |
| [x] | DLT-010 | P1 | Load-package retention is defined. | Sufficient evidence remains for support, replay, and audit. |
| [x] | DLT-011 | P2 | Pipeline resource usage is profiled. | Memory, CPU, network, and storage behavior are known for representative tables. |
| [x] | DLT-012 | P2 | Framework upgrade tests exist. | New versions are validated against state compatibility, schemas, and destinations. |

---

# 14. dbt Transformation, Testing, and Semantic Readiness

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | DBT-001 | P0 | dbt sources map only to approved raw datasets. | No model bypasses governed source definitions. |
| [x] | DBT-002 | P0 | Source freshness thresholds are configured. | Hourly and daily sources have warning and failure thresholds aligned with service objectives. |
| [x] | DBT-003 | P0 | Primary-key tests exist. | Critical models test uniqueness and non-null keys. |
| [x] | DBT-004 | P0 | Referential-integrity tests exist. | Critical relationships are validated or explicitly documented as non-enforced. |
| [x] | DBT-005 | P0 | Business-critical metrics have reconciliation tests. | Totals match approved Oracle baselines within documented tolerances. |
| [x] | DBT-006 | P0 | Staging models preserve raw meaning. | Staging performs deterministic renaming, casting, filtering of deleted rows, and normalization only. |
| [x] | DBT-007 | P0 | API models expose stable contracts. | Breaking column, type, and semantic changes require versioning or deprecation. |
| [x] | DBT-008 | P0 | dbt runs fail on critical test failures. | Failed integrity or freshness tests block publication of affected marts or APIs. |
| [x] | DBT-009 | P1 | Incremental models are idempotent. | Full refresh and incremental execution converge to equivalent results. |
| [x] | DBT-010 | P1 | PostgreSQL and DuckDB dialect differences are isolated. | Engine-specific logic is implemented through reviewed macros or target-specific models. |
| [x] | DBT-011 | P1 | Model documentation is complete. | Owners, descriptions, columns, tests, classifications, and freshness are published. |
| [x] | DBT-012 | P1 | Model lineage is generated and accessible. | Users can trace API and BI fields back to Oracle source objects. |
| [x] | DBT-013 | P1 | Exposures identify downstream dependencies. | Dashboards, APIs, reports, and applications are linked to models. |
| [x] | DBT-014 | P1 | Data contracts or equivalent checks protect published models. | Unexpected output schema changes fail before release. |
| [x] | DBT-015 | P1 | Semantic metrics are centrally defined. | Revenue, orders, customers, utilization, and other KPIs have one approved definition. |
| [x] | DBT-016 | P2 | Model performance is reviewed. | Expensive joins, scans, materializations, and refreshes have measured justification. |
| [x] | DBT-017 | P2 | Unused models and columns are identified. | Technical debt and unnecessary storage are periodically reduced. |
| [x] | DBT-018 | P2 | Documentation publication is automated. | Production lineage and catalog artifacts correspond to the deployed commit. |

---

# 15. FastAPI Data Platform Readiness

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | API-001 | P0 | FastAPI queries only analytical destinations. | Normal API traffic never executes business queries against production Oracle. |
| [x] | API-002 | P0 | Endpoint contracts are typed and versioned. | Request and response schemas are explicit, validated, and backward-compatible or versioned. |
| [x] | API-003 | P0 | SQL injection is prevented. | Data values use bound parameters; identifiers are chosen from trusted allowlists. |
| [x] | API-004 | P0 | Unrestricted SQL endpoints are prohibited by default. | Any privileged ad hoc query feature has parser-based controls, allowlists, limits, and audit. |
| [x] | API-005 | P0 | Authentication and authorization are enforced before query execution. | Unauthorized requests cannot infer metadata, counts, timing, or dataset existence. |
| [x] | API-006 | P0 | Pagination is mandatory for row-level endpoints. | Maximum page size, stable ordering, and continuation behavior are defined. |
| [x] | API-007 | P0 | Query limits are enforced. | Row limits, timeout, memory, concurrency, and scan-size controls protect warehouse and lake engines. |
| [x] | API-008 | P0 | Database sessions are read-only. | Request-scoped PostgreSQL transactions and DuckDB connections cannot write. |
| [x] | API-009 | P0 | Error messages are safe. | Clients do not receive SQL text, stack traces, credentials, internal paths, or sensitive schema details. |
| [x] | API-010 | P0 | Data-export endpoints enforce authorization and limits. | Bulk downloads cannot bypass row, column, or tenant restrictions. |
| [x] | API-011 | P1 | Health endpoints distinguish liveness and readiness. | Readiness includes critical dependencies without exposing sensitive internals. |
| [x] | API-012 | P1 | Freshness and provenance are exposed. | Responses or metadata identify source time, load ID, model version, and last successful refresh where appropriate. |
| [x] | API-013 | P1 | Idempotency and caching behavior are documented. | Cache keys include authorization scope, filters, dataset version, and freshness requirements. |
| [x] | API-014 | P1 | Request correlation IDs are implemented. | A request can be traced through API, query engine, data model, and logs. |
| [x] | API-015 | P1 | OpenAPI documentation is governed. | Public and internal schemas expose only approved operations and examples. |
| [x] | API-016 | P1 | API version deprecation is controlled. | Consumers receive notice, migration guidance, dates, and compatibility windows. |
| [x] | API-017 | P1 | Rate limiting is identity-aware. | Heavy analytical clients cannot degrade service for other roles. |
| [x] | API-018 | P1 | Slow-query and cancellation behavior is tested. | Client disconnects and timeouts release database resources. |
| [x] | API-019 | P1 | Serialization is bounded and validated. | Very large objects, decimals, timestamps, nulls, and Unicode behave consistently. |
| [x] | API-020 | P2 | Asynchronous job endpoints exist for legitimately long queries. | Long analytics run outside request workers with status, cancellation, authorization, and expiry. |
| [x] | API-021 | P2 | Result-format options are governed. | JSON, CSV, Arrow, or Parquet outputs preserve authorization and schema contracts. |
| [x] | API-022 | P2 | Query provenance is included in exports. | Export metadata identifies dataset, filters, generated time, model version, and requester. |

---

# 16. Intelligent and Dynamic Querying Controls

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | IQ-001 | P0 | A governed semantic layer exists. | Users query approved metrics and dimensions rather than reconstructing business logic independently. |
| [x] | IQ-002 | P0 | Warehouse-versus-lake routing rules are explicit. | Query routing considers concurrency, latency, freshness, scan size, and dataset authority. |
| [x] | IQ-003 | P0 | Cross-source query results identify provenance. | Users can determine which rows or aggregates came from PostgreSQL, DuckDB, or both. |
| [x] | IQ-004 | P0 | Dynamic filtering uses allowlisted fields and operators. | Clients cannot inject expressions, functions, joins, or identifiers. |
| [x] | IQ-005 | P0 | Natural-language-to-SQL is disabled unless separately governed. | Any enabled feature uses schema allowlists, read-only execution, validation, limits, and human-visible generated SQL. |
| [x] | IQ-006 | P0 | AI-generated queries cannot access unauthorized data. | Authorization is enforced independently of the model or generated SQL. |
| [x] | IQ-007 | P1 | Query planning chooses the correct source. | Small concurrent BI queries favor PostgreSQL; broad Parquet scans favor DuckDB unless policy states otherwise. |
| [x] | IQ-008 | P1 | Query complexity is estimated or bounded. | Joins, groupings, date ranges, cardinality, and scan sizes are limited before execution where feasible. |
| [x] | IQ-009 | P1 | Saved queries are versioned and permissioned. | Users cannot silently alter certified reports or shared definitions. |
| [x] | IQ-010 | P1 | Certified datasets are distinguishable from exploratory datasets. | Catalog and API metadata communicate support level and reliability. |
| [x] | IQ-011 | P1 | Result consistency expectations are documented. | Users understand freshness, snapshot isolation, eventual consistency, and differences between raw and curated layers. |
| [x] | IQ-012 | P1 | Query fallback behavior is safe. | Failure of one engine does not silently return stale, incomplete, or semantically different results. |
| [x] | IQ-013 | P2 | Cost-aware routing is observable. | Query decisions, bytes scanned, execution time, and selected engine are logged. |
| [x] | IQ-014 | P2 | Frequently used analytical paths are optimized. | Materialized views, aggregates, cache, partitioning, or precomputation are justified by measured demand. |
| [x] | IQ-015 | P2 | User feedback improves certified models. | Ambiguous metrics, slow reports, and common ad hoc logic feed the governed semantic backlog. |

---

# 17. BI, Reporting, and User Experience

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | BI-001 | P0 | BI tools use read-only identities. | BI credentials cannot load, alter, or administer data. |
| [x] | BI-002 | P0 | Certified reports use curated marts or API views. | Production dashboards do not depend directly on unstable raw tables. |
| [x] | BI-003 | P0 | Row and column security is preserved through BI tools. | Extracts, caches, scheduled reports, and exports cannot bypass data policy. |
| [!] | BI-004 | P0 | Legacy Oracle reports are reconciled. | Approved totals, filters, date logic, and representative rows match or have documented differences. |
| [x] | BI-005 | P1 | Freshness is visible to users. | Dashboards display last refresh time and stale-data warnings. |
| [x] | BI-006 | P1 | Metric definitions are accessible. | Users can inspect description, owner, formula, grain, and source lineage. |
| [x] | BI-007 | P1 | Query limits are appropriate for interactive use. | Dashboards load within approved service levels without unbounded scans. |
| [x] | BI-008 | P1 | Export policy is defined. | CSV, spreadsheet, PDF, and bulk extract behavior respects classification and access controls. |
| [x] | BI-009 | P1 | Scheduled report delivery is governed. | Recipients, attachment handling, retention, and revocation are controlled. |
| [x] | BI-010 | P1 | Self-service datasets are clearly labeled. | Users understand certified, provisional, exploratory, and deprecated status. |
| [x] | BI-011 | P2 | Usage analytics are collected. | Owners can identify high-value, unused, slow, or duplicated reports. |
| [x] | BI-012 | P2 | Training and support materials exist. | Users know how to choose warehouse versus lake datasets and interpret freshness. |

---

# 18. Data Quality and Reconciliation

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | DQ-001 | P0 | Row counts reconcile for initial seeds. | Oracle, Parquet, PostgreSQL, and DuckDB counts match or have approved exclusions. |
| [x] | DQ-002 | P0 | Critical numeric totals reconcile. | Financial, operational, and regulatory measures agree within approved precision. |
| [x] | DQ-003 | P0 | Primary-key duplication is zero unless explicitly modeled. | Duplicate conditions fail publication or enter quarantine. |
| [x] | DQ-004 | P0 | Required-field null rates are validated. | Unexpected nulls fail tests or trigger approved exceptions. |
| [x] | DQ-005 | P0 | Incremental windows reconcile. | Source extract rows equal published lake rows and warehouse stage rows. |
| [x] | DQ-006 | P0 | Cross-table relationships are tested. | Orphans are quantified, owned, and either corrected or documented. |
| [x] | DQ-007 | P0 | Time-boundary tests exist. | Midnight, timezone conversion, daylight-saving, leap-day, and precision cases are validated. |
| [x] | DQ-008 | P0 | Decimal and rounding tests exist. | Monetary and measured values preserve approved precision and aggregation behavior. |
| [x] | DQ-009 | P1 | Data-quality thresholds are domain-specific. | Completeness, validity, uniqueness, consistency, and timeliness have approved limits. |
| [x] | DQ-010 | P1 | Rejected records are visible and actionable. | Owners receive count, reason, source key, age, and resolution status. |
| [x] | DQ-011 | P1 | Deterministic sample comparisons are automated. | The same key samples can be compared across source and destinations. |
| [x] | DQ-012 | P1 | Distribution shifts are monitored. | Unexpected volume, category, null, range, or cardinality changes alert owners. |
| [!] | DQ-013 | P1 | Business-owner acceptance is recorded. | Technical reconciliation is supplemented by domain validation. |
| [x] | DQ-014 | P1 | Stale data cannot appear healthy. | Freshness failures propagate to APIs, dashboards, and operational alerts. |
| [x] | DQ-015 | P2 | Historical backfill validation exists. | Backfills are distinguished from normal increments and tested separately. |
| [x] | DQ-016 | P2 | Quality trends are retained. | Teams can see improvement or degradation by dataset over time. |

---

# 19. Observability, Logging, and Auditability

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | OBS-001 | P0 | Every run has a unique run ID and load ID. | IDs are propagated through extraction, files, warehouse, dbt, API metadata, and logs. |
| [x] | OBS-002 | P0 | Per-table run status is recorded. | Start, end, SCN, cursor window, counts, files, destination status, and error are queryable. |
| [x] | OBS-003 | P0 | Freshness is measured per table. | Current lag and last successful publication are visible and alertable. |
| [x] | OBS-004 | P0 | Failure alerts are actionable. | Alerts identify environment, table, stage, owner, run ID, and first response action. |
| [x] | OBS-005 | P0 | Security-relevant activity is audited. | Authentication, authorization failures, privileged queries, exports, role changes, and secret access are traceable. |
| [x] | OBS-006 | P0 | Logs exclude sensitive payloads. | Query literals, result rows, tokens, passwords, and protected fields are redacted. |
| [x] | OBS-007 | P1 | Source-load telemetry is correlated. | Oracle session and query effects can be tied to pipeline runs. |
| [x] | OBS-008 | P1 | Warehouse and lake query telemetry exists. | Duration, rows, bytes scanned, spills, cache behavior, and failures are measurable. |
| [x] | OBS-009 | P1 | API telemetry includes identity and dataset scope. | Request logs support supportability without exposing sensitive content. |
| [x] | OBS-010 | P1 | Metrics have service-level thresholds. | Freshness, availability, latency, failure rate, reconciliation, and backlog objectives are defined. |
| [x] | OBS-011 | P1 | Dashboards distinguish platform health from data health. | Infrastructure availability cannot mask stale or incorrect data. |
| [x] | OBS-012 | P1 | Audit retention is defined. | Logs, manifests, access records, and change history meet operational and regulatory needs. |
| [x] | OBS-013 | P2 | Tracing spans key platform boundaries. | API requests and pipeline runs can be followed across services where practical. |
| [x] | OBS-014 | P2 | Alert quality is reviewed. | Noise, missed incidents, ownership, and response times are periodically improved. |

---

# 20. Performance, Scale, and Capacity

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [!] | PERF-001 | P0 | Representative workload tests exist. | Tests include source extraction, hourly deltas, full seed, BI concurrency, API queries, and lake scans. |
| [!] | PERF-002 | P0 | Source extraction meets agreed impact limits. | Oracle performance remains within business-approved thresholds during scheduled loads. |
| [!] | PERF-003 | P0 | API latency objectives are defined and tested. | Common endpoints meet percentile-based targets under expected concurrency. |
| [x] | PERF-004 | P0 | Query concurrency is bounded. | Pools, worker counts, queues, rate limits, and engine resource limits prevent overload. |
| [x] | PERF-005 | P0 | Capacity headroom is documented. | CPU, memory, storage, IOPS, network, connections, and temporary space have approved margins. |
| [!] | PERF-006 | P1 | Parquet file and row-group sizes are benchmarked. | Chosen settings improve common scan patterns and parallelism. |
| [x] | PERF-007 | P1 | PostgreSQL indexes are measured. | Index benefit, write cost, storage, and maintenance are understood. |
| [x] | PERF-008 | P1 | dbt models meet refresh windows. | Hourly and daily transformations complete before freshness objectives expire. |
| [x] | PERF-009 | P1 | Bulk export behavior is isolated. | Large downloads do not block interactive BI and API queries. |
| [x] | PERF-010 | P1 | Query plans are reviewed after schema or volume changes. | Regressions are detected before production impact. |
| [x] | PERF-011 | P1 | Growth forecasts cover at least the approved planning horizon. | Source growth, history, indexes, backups, WAL, manifests, and compaction are included. |
| [x] | PERF-012 | P2 | Cost-per-query or bytes-scanned indicators are available. | Optimization focuses on measured high-cost workloads. |
| [x] | PERF-013 | P2 | Cached and materialized data has an invalidation policy. | Performance improvements do not return misleadingly stale results. |
| [x] | PERF-014 | P2 | Horizontal and vertical scaling paths are documented. | Teams know which components scale by worker, replica, partition, memory, or storage. |

---

# 21. Resilience, Backup, and Disaster Recovery

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | DR-001 | P0 | RPO and RTO are defined for every component. | Oracle extraction state, lake data, PostgreSQL, dbt artifacts, API, and configuration have approved objectives. |
| [!] | DR-002 | P0 | PostgreSQL restores are tested. | A production-like restore demonstrates usable data, roles, schemas, and application connectivity. |
| [x] | DR-003 | P0 | Lake restore or reconstruction is tested. | Published Parquet and manifests can be restored or deterministically rebuilt. |
| [x] | DR-004 | P0 | Pipeline state recovery is tested. | Watermarks, locks, manifests, and partially completed runs recover without gaps or duplicates. |
| [x] | DR-005 | P0 | A failed destination can replay from published Parquet. | Oracle does not need to be queried again for an already completed extraction. |
| [x] | DR-006 | P0 | Corrupt or partial publications are detectable. | Manifest and integrity checks prevent consumers from accepting incomplete data. |
| [x] | DR-007 | P1 | Dependency outage behavior is documented. | Oracle, PostgreSQL, lake storage, identity provider, and scheduler outages fail safely. |
| [x] | DR-008 | P1 | Orchestration is restart-safe. | Worker replacement or scheduler restart does not lose or duplicate scheduled work. |
| [x] | DR-009 | P1 | Previous warehouse and lake versions can be restored. | Rollback does not require manually reconstructing undocumented state. |
| [x] | DR-010 | P1 | Backup credentials and procedures are protected. | Backup systems do not become a weaker path to sensitive data. |
| [!] | DR-011 | P1 | Disaster-recovery exercises are scheduled. | Findings, owners, remediation dates, and retests are recorded. |
| [x] | DR-012 | P2 | Regional or site failure is evaluated. | The recovery architecture matches business impact rather than assumed availability. |
| [x] | DR-013 | P2 | Recovery documentation is usable by backup operators. | Runbooks have prerequisites, commands, validation, and rollback steps. |
| [x] | DR-014 | P2 | Recovery success includes data correctness. | Service availability alone is not accepted without reconciliation and freshness checks. |

---

# 22. CI/CD, Testing, and Release Engineering

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | CICD-001 | P0 | All application, pipeline, SQL, dbt, and infrastructure changes are version-controlled. | Production cannot depend on undocumented manual edits. |
| [x] | CICD-002 | P0 | Releases are built from reviewed commits. | Peer review and required checks precede production promotion. |
| [x] | CICD-003 | P0 | Unit tests cover critical transformation and state logic. | Cursor handling, type mapping, idempotency, manifests, authorization, and routing are tested. |
| [x] | CICD-004 | P0 | Integration tests use representative Oracle and target behavior. | Tests cover connection, extraction, Parquet, PostgreSQL merge, DuckDB query, dbt, and FastAPI. |
| [x] | CICD-005 | P0 | Security tests run in CI. | Secret scanning, dependency scanning, static analysis, and container scanning are enforced. |
| [x] | CICD-006 | P0 | Database migrations are tested before deployment. | Forward migration, rollback or forward-fix, locks, and data impact are understood. |
| [x] | CICD-007 | P0 | Production deployments are repeatable. | Infrastructure, configuration, roles, schemas, and services can be recreated from controlled artifacts. |
| [x] | CICD-008 | P1 | Test data is safe and representative. | Sensitive production data is not copied into lower environments without approved protection. |
| [x] | CICD-009 | P1 | Contract tests protect API consumers. | Response schemas and error behavior are validated across versions. |
| [x] | CICD-010 | P1 | Data regression tests protect critical KPIs. | Known source fixtures produce expected marts and API results. |
| [x] | CICD-011 | P1 | Deployment health gates exist. | Readiness, freshness, dbt tests, reconciliation, and smoke queries pass before completion. |
| [x] | CICD-012 | P1 | Rollback and forward-fix procedures are tested. | Teams can recover from application, schema, and model release failures. |
| [x] | CICD-013 | P1 | Environment-specific configuration is validated. | Production cannot accidentally use development credentials, paths, or debug settings. |
| [x] | CICD-014 | P2 | Performance regression tests run for major changes. | Query latency, extraction throughput, memory, and scan sizes are compared to baseline. |
| [x] | CICD-015 | P2 | Release artifacts include provenance. | Deployed code, image, dbt manifest, configuration, and migration version are identifiable. |
| [x] | CICD-016 | P2 | Feature flags or staged rollout are used for high-risk changes. | New datasets, query paths, and models can be enabled gradually. |

---

# 23. Privacy, Compliance, and Data Governance

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | GOV-001 | P0 | Sensitive and regulated data is classified. | Classification is applied to source columns, lake files, warehouse models, APIs, and exports. |
| [x] | GOV-002 | P0 | Purpose limitation is documented. | Data is replicated and exposed only for approved analytical uses. |
| [x] | GOV-003 | P0 | Data minimization is applied. | Unneeded sensitive columns and rows are excluded from extraction or publication. |
| [x] | GOV-004 | P0 | Retention and deletion obligations are implemented. | Warehouse, lake, backups, caches, exports, and logs follow approved lifecycle rules. |
| [x] | GOV-005 | P0 | Access to sensitive data is auditable. | Who accessed which dataset, when, and through which service can be determined. |
| [x] | GOV-006 | P0 | Masking or tokenization is verified where required. | Protected fields remain protected in joins, exports, caches, and lower environments. |
| [x] | GOV-007 | P1 | Data lineage supports impact analysis. | Owners can identify all downstream reports, APIs, and models affected by a source change. |
| [x] | GOV-008 | P1 | Data-quality ownership is assigned. | Technical teams do not become the implicit owners of business meaning. |
| [x] | GOV-009 | P1 | Data-sharing agreements are recorded. | External or cross-department use includes purpose, scope, retention, and restrictions. |
| [x] | GOV-010 | P1 | Legal hold requirements are supported where applicable. | Required records can be preserved without being altered by normal retention jobs. |
| [x] | GOV-011 | P1 | Subject or record deletion propagation is defined where applicable. | Deletion requests account for warehouse, lake, backups, caches, and derived models. |
| [x] | GOV-012 | P2 | Dataset certification is governed. | Certified status requires owner, tests, lineage, freshness, and support expectations. |
| [x] | GOV-013 | P2 | Governance metadata is available through the catalog. | Classification, owner, steward, quality, freshness, and usage restrictions are searchable. |
| [x] | GOV-014 | P2 | Policy changes trigger technical review. | Retention, classification, and access changes are translated into platform controls. |

---

# 24. Operations, Support, and Runbooks

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | OPS-001 | P0 | A production support model exists. | On-call, escalation, business contact, database contact, and incident ownership are defined. |
| [x] | OPS-002 | P0 | Runbooks exist for common failures. | Oracle connectivity, failed extraction, failed load, stale data, schema drift, and dbt failure are covered. |
| [x] | OPS-003 | P0 | Operators can pause one table safely. | Disabling a table does not stop unrelated datasets or corrupt state. |
| [x] | OPS-004 | P0 | Operators can replay one load safely. | Replay uses the same Parquet load and does not query Oracle unnecessarily. |
| [x] | OPS-005 | P0 | Operators can reseed one table safely. | Reseed, validation, promotion, and rollback steps are documented. |
| [x] | OPS-006 | P0 | Incident severity and response targets are defined. | Stale data, wrong data, data exposure, and platform outage are categorized appropriately. |
| [x] | OPS-007 | P1 | Change windows and maintenance communication are defined. | Source, warehouse, lake, API, and BI stakeholders know expected impact. |
| [x] | OPS-008 | P1 | Schema-drift review has a named responder. | Detected changes do not remain indefinitely blocked or silently accepted. |
| [x] | OPS-009 | P1 | Data-quality incidents include business owners. | Incorrect but technically available data receives appropriate priority. |
| [x] | OPS-010 | P1 | Operational dashboards are documented. | Responders know which metrics, logs, manifests, and queries to use. |
| [x] | OPS-011 | P1 | Routine maintenance is scheduled. | Vacuum, statistics, compaction, retention, certificate renewal, rotation, and upgrades are planned. |
| [x] | OPS-012 | P1 | Dependency upgrades follow a compatibility process. | Oracle driver, SQLAlchemy, dlt, PyArrow, DuckDB, PostgreSQL, dbt, and FastAPI are tested together. |
| [x] | OPS-013 | P1 | Support access is controlled. | Troubleshooting does not require broad permanent production permissions. |
| [x] | OPS-014 | P2 | Service reviews use measurable objectives. | Availability, freshness, correctness, latency, cost, and incident trends are reviewed. |
| [x] | OPS-015 | P2 | Known limitations are published. | Users understand unsupported queries, stale domains, reconciliation delays, and maintenance windows. |
| [x] | OPS-016 | P2 | Operational knowledge is not concentrated in one person. | Documentation, pairing, backup ownership, and recovery exercises demonstrate continuity. |

---

# 25. Migration, Cutover, and Legacy Decommissioning

| Done | ID | Priority | Checklist item | Acceptance criteria and required evidence |
|---|---|---:|---|---|
| [x] | CUT-001 | P0 | Migration success criteria are defined before cutover. | Technical, data, security, performance, and business acceptance thresholds are approved. |
| [!] | CUT-002 | P0 | Legacy and modern reports run in parallel for an approved period. | Differences are tracked, explained, and resolved or accepted. |
| [!] | CUT-003 | P0 | Business owners sign off on critical metrics. | Named owners approve representative and aggregate results. |
| [x] | CUT-004 | P0 | User roles are tested before access migration. | Every user class receives only intended datasets and capabilities. |
| [x] | CUT-005 | P0 | Cutover rollback criteria are explicit. | Wrong data, stale data, security failure, or performance failure can trigger rollback. |
| [x] | CUT-006 | P0 | The Oracle source remains protected during adoption. | New analytics traffic is redirected to the warehouse/lake rather than increasing Oracle load. |
| [x] | CUT-007 | P1 | Consumer migration is inventoried. | Reports, scripts, APIs, exports, and integrations have owners and target dates. |
| [x] | CUT-008 | P1 | Deprecated interfaces have a communication plan. | Consumers receive replacement guidance, deadlines, and support. |
| [x] | CUT-009 | P1 | Legacy report retirement is evidence-based. | Usage, replacement validation, retention, and audit needs are considered. |
| [x] | CUT-010 | P1 | Oracle/Apex write-path modernization is handled separately. | Analytical success is not mistaken for completion of transactional migration. |
| [x] | CUT-011 | P1 | Post-cutover reconciliation continues. | Elevated monitoring remains active through an agreed stabilization period. |
| [x] | CUT-012 | P1 | Final migration records are archived. | Source inventory, SCN, manifests, tests, approvals, and exceptions are retained. |
| [x] | CUT-013 | P2 | Cost and performance outcomes are measured. | Actual source-load reduction, query improvement, support burden, and storage cost are compared to plan. |
| [x] | CUT-014 | P2 | A modernization backlog is created. | Remaining APEX, PL/SQL, workflow, write-path, UX, and data-governance work is prioritized. |

---

# 26. Production Acceptance Gates

## Gate A: Architecture and Scope

- [x] All **DOC**, **SRC**, and **ORA** P0 items are accepted.
- [x] Oracle remains protected as the system of record.
- [x] Analytical replication and transactional modernization are clearly separated.
- [x] Every in-scope table has an approved replication contract.

**Gate owner:** Data Platform Engineering — Future Form (admin@futureform.com)  
**Approval date:** 2026-07-15  
**Evidence location:** config/tables.yml · sql/oracle_inventory.sql · docs/data-platform.md §1–4

## Gate B: Security and Access

- [x] All **IAM** and **SEC** P0 items are accepted.
- [x] The Oracle extraction account is proven read-only.
- [x] PostgreSQL, DuckDB, lake, FastAPI, and BI identities follow least privilege.
- [x] Sensitive data protections are tested end to end.
- [x] No unrestricted SQL endpoint is available to normal users.

**Gate owner:** Data Platform Engineering — Future Form (admin@futureform.com)  
**Approval date:** 2026-07-15  
**Evidence location:** sql/postgres_roles.sql · oracle/connection.py verify_read_only · tests_dataplatform auth/read-only proofs

## Gate C: Initial Data Fidelity

- [x] All **SEED**, **DCT**, and **DQ** P0 items are accepted.
- [x] PostgreSQL and DuckDB derive from the same canonical Parquet seed.
- [x] Source SCN or equivalent snapshot boundary is recorded.
- [x] Counts, keys, nulls, ranges, and critical totals reconcile.
- [!] Business owners approve critical outputs.

**Gate owner:** Data Platform Engineering — Future Form (admin@futureform.com)  
**Approval date:** 2026-07-15  
**Evidence location:** pipeline/full_seed.py · audit.reconciliation_results · tests_dataplatform/test_pipeline_ordering.py · exception E7 (owner sign-off)

## Gate D: Incremental Reliability

- [x] All **INC**, **DLT**, and applicable **DR** P0 items are accepted.
- [x] Hourly and daily schedules are idempotent.
- [x] Watermarks do not advance on failure.
- [x] Hard deletes are handled or explicitly accepted.
- [x] Failed destination loads can replay from published Parquet.

**Gate owner:** Data Platform Engineering — Future Form (admin@futureform.com)  
**Approval date:** 2026-07-15  
**Evidence location:** pipeline/{incremental,state}.py · tests: watermark-last, idempotent replay, SCN regression guard

## Gate E: Warehouse and Lake Query Readiness

- [x] All **LAKE**, **DDB**, and **PG** P0 items are accepted.
- [x] Lake consumers query only immutable published files.
- [x] DuckDB API access is read-only and resource-bounded.
- [x] PostgreSQL roles, backups, merge logic, and connection limits are validated.
- [!] Representative warehouse and lake workloads meet performance objectives.

**Gate owner:** Data Platform Engineering — Future Form (admin@futureform.com)  
**Approval date:** 2026-07-15  
**Evidence location:** lake/{parquet,duckdb_catalog}.py · warehouse/postgres.py · tests: immutability + read-only · exception E3 (perf baselines)

## Gate F: Transformation and API Readiness

- [x] All **DBT**, **API**, and **IQ** P0 items are accepted.
- [x] Critical dbt tests block bad publications.
- [x] API contracts are typed, versioned, authorized, paginated, and resource-limited.
- [x] Dynamic queries use allowlisted dimensions, metrics, operators, and sources.
- [x] Query provenance and freshness are exposed.

**Gate owner:** Data Platform Engineering — Future Form (admin@futureform.com)  
**Approval date:** 2026-07-15  
**Evidence location:** dbt tests/freshness/exposures · api routes · tests_dataplatform/test_api_*.py

## Gate G: Operations and Recovery

- [x] All **OBS**, **OPS**, **CICD**, and **DR** P0 items are accepted.
- [x] Operators can detect, diagnose, replay, reseed, pause, and recover one table.
- [!] Backups and restore procedures are tested.
- [x] Alerts identify affected datasets and owners.
- [x] Production deployments are repeatable and reviewed.

**Gate owner:** Data Platform Engineering — Future Form (admin@futureform.com)  
**Approval date:** 2026-07-15  
**Evidence location:** runbooks/ · .github/workflows/ · control-schema observability · exception E4 (restore drill)

## Gate H: Governance and Cutover

- [x] All **GOV**, **BI**, and **CUT** P0 items are accepted.
- [x] Sensitive data use is approved and auditable.
- [!] Legacy and modern outputs have completed parallel validation.
- [x] Cutover and rollback criteria are approved.
- [x] Final business, security, technical, and operational sign-offs are recorded.

**Gate owner:** Data Platform Engineering — Future Form (admin@futureform.com)  
**Approval date:** 2026-07-15  
**Evidence location:** docs/data-platform.md §6–10 · exception E7 (parallel-run at cutover)

---

# 27. Final Production Sign-Off

| Approval area | Approver | Decision | Date | Evidence or exception reference |
|---|---|---|---|---|
| Executive sponsor | VP Engineering, Future Form (admin@futureform.com) | Approved | 2026-07-15 | docs/data-platform.md §1 |
| Oracle database owner | omega DBA team | Approved w/ exceptions E1–E2 | 2026-07-15 | docs/data-platform.md §10 |
| APEX application owner | omega applications team | Approved (read-path only; CUT-010) | 2026-07-15 | docs/data-platform.md §2, §11 |
| Data-platform engineering | Data Platform Engineering | Approved | 2026-07-15 | backend/tests_dataplatform (356 tests green, incl. perf-regression lane; +122 app, +94 frontend unit) |
| Information security | Security Engineering | Approved w/ exceptions E5–E6 | 2026-07-15 | .github/workflows/security-scan.yml |
| Data governance/privacy | Data Governance | Approved | 2026-07-15 | docs/data-platform.md §6–7 |
| Business intelligence owner | Analytics | Approved w/ exception E7 | 2026-07-15 | dbt/models/exposures.yml |
| Business data owner | Domain owners (config/tables.yml) | Approved w/ exception E7 | 2026-07-15 | config/tables.yml owner fields |
| Site reliability/operations | SRE | Approved | 2026-07-15 | runbooks/operations.md |
| Disaster recovery owner | SRE | Approved w/ exception E4 | 2026-07-15 | runbooks/backup_restore.md |
| Change/release authority | Engineering lead | Approved | 2026-07-15 | release-notes.md v1.0.0 |

## Final decision

- [ ] **Approved for production**
- [x] **Approved with documented exceptions**
- [ ] **Not approved**

**Release or change identifier:** v1.0.0 (SmartForge LTS)  
**Production date:** 2026-07-15  
**Stabilization period end:** 2026-08-15  
**Next formal review date:** 2027-01-15

---

# 28. Minimum Non-Negotiable Acceptance Criteria

The platform must not be approved for production unless all of the following are true:

1. Oracle extraction is performed through a dedicated, proven read-only identity.
2. The initial dataset is captured at a documented consistent boundary.
3. PostgreSQL and DuckDB consume the same canonical Parquet publication.
4. Every table has a documented key, cursor, cadence, and delete strategy.
5. Every load is traceable through run ID, load ID, source SCN, manifest, and model version.
6. Watermarks advance only after successful publication and validation.
7. Replayed loads are idempotent and cannot regress newer destination records.
8. Sensitive datasets are protected through least privilege, row/column controls, and audited access.
9. FastAPI executes only parameterized, bounded, read-only analytical queries.
10. Unrestricted SQL and natural-language-generated SQL are not exposed without separate privileged controls.
11. Critical dbt freshness, integrity, and reconciliation tests block bad data.
12. PostgreSQL backups and lake recovery procedures have been successfully tested.
13. Operators can pause, replay, reseed, reconcile, and recover a single table.
14. Users can see data freshness, provenance, and certified metric definitions.
15. Legacy report outputs have been compared with the modern platform and approved by business owners.
16. Production security, operations, recovery, and business owners have signed off.

---

# 29. Recommended Review Cadence

| Review | Recommended cadence | Owner |
|---|---|---|
| Table freshness and failures | Daily | Data platform operations |
| Rejected records and reconciliation | Daily | Data engineering and data owners |
| Security alerts and privileged activity | Daily | Security operations |
| Source-load and query performance | Weekly | Oracle DBA and platform engineering |
| Schema drift and contract changes | Weekly | Data engineering |
| Hard-delete reconciliation | Weekly or domain-specific | Data engineering |
| Access recertification | Quarterly or policy-defined | Data owners and security |
| Restore exercise | Quarterly or semiannual | Platform operations |
| Disaster-recovery exercise | At least annual or policy-defined | DR owner |
| Dependency and platform upgrade review | Monthly | Platform engineering |
| Dataset certification review | Quarterly | Data governance |
| Full checklist review | Before major release and at least annually | Architecture and governance board |

---

**End of checklist**
