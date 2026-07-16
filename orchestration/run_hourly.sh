#!/usr/bin/env bash
# Hourly platform dispatch — cron entrypoint (Phase 0).
#   crontab: 0 * * * * /path/to/smartforge/orchestration/run_hourly.sh
# Single-flight is enforced inside `dispatch` via a Postgres advisory lock.
# Non-zero exit must be wired to alerting (Migration §9: fail loud).
set -euo pipefail

cd "$(dirname "$0")/../backend"
exec uv run python -m app.dataplatform.cli dispatch
