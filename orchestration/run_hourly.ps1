# Hourly platform dispatch — Windows Task Scheduler entrypoint (Phase 0).
# Schedule: every hour, on the hour, under a service account.
# Single-flight is enforced inside `dispatch` via a Postgres advisory lock,
# so an over-running tick never overlaps the next trigger (INC-013).
# Non-zero exit -> Task Scheduler failure -> alert (Migration §9).

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\backend")

uv run python -m app.dataplatform.cli dispatch
exit $LASTEXITCODE
