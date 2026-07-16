# Contributing to SmartForge

**SmartForge v1.0.0 LTS** — thank you for contributing. This guide covers
the workflow for changes to this repository; platform knowledge lives in
[`CLAUDE.md`](CLAUDE.md) and the specification of record in
[`specs/ARCHITECTURE.md`](specs/ARCHITECTURE.md).

## Before you start

- **Big changes** (new features, architectural changes, new replication
  contracts, schema changes to certified `api_*`/mart models): open a
  discussion/issue first. Changes to the analytics platform must respect
  the invariants in `CLAUDE.md` §7.3 and the acceptance checklist
  ([`specs/CHECKLIST.md`](specs/CHECKLIST.md)) — anything that would
  re-mark a checklist item needs a reviewer from Data Platform Engineering.
- **Small changes** (typos, lint fixes, small reproducible bug fixes) can
  go straight to a PR.
- Dependency changes require review: backend pins live in
  `backend/pyproject.toml` + `uv.lock`, frontend in
  `frontend/package.json` (linters pinned exactly). See
  `runbooks/operations.md` §Dependency upgrades for the DuckDB/dbt lanes.

## Development setup

See the [Development Guide](development.md). Quick loop:

```bash
cd backend && uv sync && uv run pytest tests_smartforge tests_dataplatform -q
cd frontend && bun install && bun run lint && bun run test:unit
```

## The bar every PR must clear

The **`ci-pipeline`** workflow is the merge gate — its single
`pipeline-confidence` status must be green. It runs, with zero external
services: backend ruff + mypy, the full offline test matrix
(356 platform + 122 app + 94 frontend unit = **572 tests**), dbt parse on
both targets + docs artifact, and the compose/Helm/preflight contract
checks. Run everything locally first (`CLAUDE.md` §9 has the commands).

Additional expectations:

1. Keep PRs focused on a single change; update tests with functionality.
2. Follow the conventions in `CLAUDE.md` §10 (docstrings state purpose and
   constraint with checklist IDs; comments explain *why*; dialect-neutral
   dbt SQL; secrets never in code/config/logs).
3. New governed datasets: contract in `config/tables.yml` → dbt model +
   `schema.yml` tests → exposure registration → offline tests.
4. `.env.example` is test-pinned to code defaults
   (`tests_dataplatform/test_config_drift.py`) — change both together.

## Versioning

Semver; **v1.0.0 is the LTS baseline**. One version, everywhere: the API
(`/api/v1`, FastAPI `version`), `backend/pyproject.toml`,
`frontend/package.json`, the Helm chart (`version`/`appVersion`), and the
dbt project all state `1.0.0`. Breaking API changes ship under a new
version prefix with deprecation guidance (API-016); release notes in
[`release-notes.md`](release-notes.md); the acceptance checklist is
re-reviewed each major release.

## Automated code and AI

Use whatever tools make you effective, including AI — but contributions
must reflect meaningful human judgement. If the human effort in a PR is
less than the effort required to review it, don't submit it. Low-effort
automated PRs and comments will be closed.

## Provenance

Built on the excellent
[Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template)
(MIT); template-inherited workflows keep upstream conventions where they
still apply.
