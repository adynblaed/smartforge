"""Data-platform operator CLI.

python -m app.dataplatform.cli preflight        # config/credential/connectivity checks
python -m app.dataplatform.cli bootstrap        # warehouse db/schemas/roles/control tables
python -m app.dataplatform.cli discover         # infer schemas from omega (read-only)
python -m app.dataplatform.cli plan             # show the latest proposed seed plan
python -m app.dataplatform.cli seed --plan-id X # confirm + execute a seed (interactive)
python -m app.dataplatform.cli sync [--cadence hourly]
python -m app.dataplatform.cli reconcile-deletes
python -m app.dataplatform.cli dbt [--target warehouse|lake]
python -m app.dataplatform.cli dispatch         # one scheduler tick
python -m app.dataplatform.cli freshness
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from app.core.logging_config import setup_logging

setup_logging()
logger = logging.getLogger("dataplatform.cli")


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, default=str))  # noqa: T201


def cmd_preflight(args: argparse.Namespace) -> int:
    """Validate configuration, credentials, and connectivity before any
    pipeline operation (CICD-011 deployment health gate).

    Local/CI checks (config, contracts, lake paths, dbt project) always
    gate the exit code. Connectivity checks (Oracle, warehouse, catalog)
    gate it too unless --tolerate-unreachable is passed, which reports
    them without failing — useful in sandboxes without live services.
    """
    from sqlalchemy import create_engine, text

    from app.dataplatform.config import get_platform_settings
    from app.dataplatform.registry import load_registry, load_type_mappings

    settings = get_platform_settings()
    checks: list[dict[str, str]] = []
    hard_failed = False
    soft_failed = False

    def record(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    # -- Configuration & contracts (always gating) ----------------------
    try:
        registry = load_registry()
        load_type_mappings()
        record(
            "config.contracts",
            "ok",
            f"{len(registry.contracts)} table contracts validated",
        )
    except Exception as exc:  # noqa: BLE001 - report every failure kind
        record("config.contracts", "fail", str(exc))
        hard_failed = True

    # Known-default values raise at settings load (PlatformSettings validator);
    # preflight additionally fails EMPTY credentials in any non-development
    # environment (staging included) so a half-configured deploy is caught.
    if settings.PLATFORM_ENV != "development":
        missing = [
            name
            for name, value in (
                ("OMEGA_ORACLE_PASSWORD", settings.OMEGA_ORACLE_PASSWORD),
                ("WAREHOUSE_LOADER_PASSWORD", settings.WAREHOUSE_LOADER_PASSWORD),
                ("WAREHOUSE_DBT_PASSWORD", settings.WAREHOUSE_DBT_PASSWORD),
                ("WAREHOUSE_API_PASSWORD", settings.WAREHOUSE_API_PASSWORD),
            )
            if not value
        ]
        if missing:
            record(
                "config.secrets",
                "fail",
                f"unset secrets in {settings.PLATFORM_ENV}: {missing}",
            )
            hard_failed = True
        else:
            record("config.secrets", "ok", "all platform credentials injected")
    else:
        record("config.secrets", "ok", f"PLATFORM_ENV={settings.PLATFORM_ENV}")

    # -- Lake paths (always gating) --------------------------------------
    try:
        for path in (
            settings.lake_staging_dir,
            settings.lake_published_dir,
            settings.lake_quarantine_dir,
            settings.DUCKDB_PATH.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)
        probe = settings.lake_staging_dir / ".preflight_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        record("lake.paths", "ok", f"lake root writable at {settings.LAKE_ROOT}")
    except OSError as exc:
        record("lake.paths", "fail", f"lake root not writable: {exc}")
        hard_failed = True

    # -- dbt project (always gating) --------------------------------------
    if (settings.dbt_project_dir / "dbt_project.yml").is_file() and (
        settings.dbt_project_dir / "profiles.yml"
    ).is_file():
        record("dbt.project", "ok", str(settings.dbt_project_dir))
    else:
        record(
            "dbt.project", "fail", f"dbt project missing at {settings.dbt_project_dir}"
        )
        hard_failed = True

    # -- Oracle source (connectivity) -------------------------------------
    try:
        from app.dataplatform.oracle.connection import (
            oracle_connection,
            verify_read_only,
        )

        with oracle_connection() as connection:
            evidence = verify_read_only(connection)
        record(
            "oracle.read_only",
            "ok",
            f"connected as {settings.OMEGA_ORACLE_USER}; "
            f"{len(evidence['session_privileges'])} privileges, none writable",
        )
    except PermissionError as exc:
        # A writable extraction identity is ALWAYS fatal (ORA-002/003).
        record("oracle.read_only", "fail", str(exc))
        hard_failed = True
    except Exception as exc:  # noqa: BLE001 - connectivity, not privilege
        record("oracle.read_only", "unreachable", str(exc))
        soft_failed = True

    # -- Warehouse roles (connectivity) ------------------------------------
    for role, dsn in (
        ("loader", settings.warehouse_loader_dsn),
        ("transformer", settings.warehouse_dbt_dsn),
        ("api_reader", settings.warehouse_api_dsn),
    ):
        try:
            engine = create_engine(dsn, connect_args={"connect_timeout": 5})
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                record(f"warehouse.{role}", "ok", "authenticated")
            finally:
                engine.dispose()
        except Exception as exc:  # noqa: BLE001 - connectivity probe
            record(f"warehouse.{role}", "unreachable", type(exc).__name__)
            soft_failed = True

    # -- DuckDB catalog (connectivity/readability) --------------------------
    if settings.DUCKDB_PATH.is_file():
        try:
            import duckdb

            catalog_conn = duckdb.connect(str(settings.DUCKDB_PATH), read_only=True)
            try:
                views = catalog_conn.execute(
                    "SELECT count(*) FROM information_schema.tables"
                ).fetchone()
            finally:
                catalog_conn.close()
            record("duckdb.catalog", "ok", f"{views[0] if views else 0} relations")
        except Exception as exc:  # noqa: BLE001 - catalog probe
            record("duckdb.catalog", "unreachable", str(exc))
            soft_failed = True
    else:
        record(
            "duckdb.catalog", "ok", "catalog not created yet (built on first publish)"
        )

    failed = hard_failed or (soft_failed and not args.tolerate_unreachable)
    _print({"status": "fail" if failed else "ok", "checks": checks})
    return 1 if failed else 0


def cmd_bootstrap(_: argparse.Namespace) -> int:
    from app.dataplatform.warehouse.postgres import bootstrap_warehouse

    bootstrap_warehouse()
    return 0


def cmd_discover(_: argparse.Namespace) -> int:
    from app.dataplatform.pipeline import plans

    plan = plans.discover()
    _print(
        {
            "plan_id": plan.plan_id,
            "fingerprint": plan.fingerprint(),
            "tables": [
                {
                    "table": t.contract.qualified_name,
                    "columns": len(t.columns),
                    "estimated_rows": t.estimated_rows,
                    "pk_verified": t.primary_key_verified,
                    "cursor_verified": t.cursor_verified,
                    "warnings": t.warnings,
                }
                for t in plan.tables
            ],
            "blocking_issues": plan.blocking_issues,
            "seedable": plan.is_seedable,
        }
    )
    return 0 if plan.is_seedable else 1


def cmd_plan(_: argparse.Namespace) -> int:
    from app.dataplatform.pipeline import plans

    plan = plans.latest_plan()
    if plan is None:
        _print({"error": "no seed plan; run `discover` first"})
        return 1
    _print(json.loads(plan.model_dump_json()))
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from app.dataplatform.pipeline import plans
    from app.dataplatform.pipeline.full_seed import run_full_seed

    plan = plans.latest_plan()
    if plan is None:
        _print({"error": "no seed plan; run `discover` first"})
        return 1
    if args.plan_id and args.plan_id != plan.plan_id:
        _print(
            {"error": f"latest reviewable plan is {plan.plan_id}, not {args.plan_id}"}
        )
        return 1

    print(f"Seed plan {plan.plan_id} (fingerprint {plan.fingerprint()})")  # noqa: T201
    for table in plan.tables:
        print(  # noqa: T201
            f"  {table.contract.qualified_name:40s}"
            f" rows~{table.estimated_rows or '?'} warnings={len(table.warnings)}"
        )
    if plan.blocking_issues:
        print("BLOCKING ISSUES:")  # noqa: T201
        for issue in plan.blocking_issues:
            print(f"  ! {issue}")  # noqa: T201
        return 1

    if args.yes_i_reviewed_the_plan:
        phrase = plans.CONFIRMATION_PHRASE
    else:
        phrase = input(  # This seeds a warehouse — deliberate human gate.
            f"Type '{plans.CONFIRMATION_PHRASE}' to confirm seeding from the "
            "omega source (read-only): "
        ).strip()
    try:
        confirmed = plans.confirm_plan(
            plan.plan_id, plan.fingerprint(), phrase, confirmed_by="cli"
        )
    except plans.PlanNotConfirmedError as exc:
        _print({"error": str(exc)})
        return 1

    from app.dataplatform.pipeline import state as pipeline_state

    try:
        # Single-flight (INC-013): a CLI seed must never overlap a running
        # dispatcher tick or an API-triggered pipeline run.
        with pipeline_state.pipeline_lock():
            result = run_full_seed(confirmed, tables=args.tables)
    except pipeline_state.PipelineBusyError as exc:
        _print({"error": str(exc)})
        return 1
    plans.mark_executed(plan.plan_id, result)
    _print(result)
    return 0 if result["status"] == "succeeded" else 1


def cmd_sample_seed(args: argparse.Namespace) -> int:
    from app.dataplatform.pipeline.sample_seed import (
        SampleSeedRefusedError,
        run_sample_seed,
    )

    try:
        result = run_sample_seed(tables=args.tables, with_dbt=not args.skip_dbt)
    except SampleSeedRefusedError as exc:
        _print({"error": str(exc)})
        return 1
    _print(result)
    return 0 if result["status"] == "succeeded" else 1


def cmd_sync(args: argparse.Namespace) -> int:
    from app.dataplatform.pipeline import state as pipeline_state
    from app.dataplatform.pipeline.incremental import run_incremental

    try:
        with pipeline_state.pipeline_lock():
            result = run_incremental(args.cadence, tables=args.tables)
    except pipeline_state.PipelineBusyError as exc:
        _print({"error": str(exc)})
        return 1
    _print(result)
    return 0 if not result["failures"] else 1


def cmd_reconcile_deletes(args: argparse.Namespace) -> int:
    from app.dataplatform.pipeline import state as pipeline_state
    from app.dataplatform.pipeline.reconcile_deletes import run_delete_reconciliation

    try:
        with pipeline_state.pipeline_lock():
            result = run_delete_reconciliation(tables=args.tables)
    except pipeline_state.PipelineBusyError as exc:
        _print({"error": str(exc)})
        return 1
    _print(result)
    return 0 if not result["failures"] else 1


def cmd_dbt(args: argparse.Namespace) -> int:
    from app.dataplatform.pipeline.dispatcher import run_dbt

    try:
        _print(run_dbt(args.target))
        return 0
    except RuntimeError as exc:
        _print({"error": str(exc)})
        return 1


def cmd_dispatch(args: argparse.Namespace) -> int:
    from app.dataplatform.pipeline.dispatcher import dispatch

    result = dispatch(with_dbt=not args.no_dbt)
    _print(result)
    return 0 if result.get("status") in ("succeeded", "skipped") else 1


def cmd_freshness(_: argparse.Namespace) -> int:
    from app.dataplatform.pipeline.freshness import table_freshness

    report = table_freshness()
    _print(report)
    return 0 if all(r["status"] in ("fresh", "warning") for r in report) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dataplatform")
    sub = parser.add_subparsers(dest="command", required=True)

    preflight = sub.add_parser("preflight")
    preflight.add_argument(
        "--tolerate-unreachable",
        action="store_true",
        help="Report (but do not fail on) unreachable external services",
    )
    preflight.set_defaults(func=cmd_preflight)

    sub.add_parser("bootstrap").set_defaults(func=cmd_bootstrap)
    sub.add_parser("discover").set_defaults(func=cmd_discover)
    sub.add_parser("plan").set_defaults(func=cmd_plan)

    seed = sub.add_parser("seed")
    seed.add_argument("--plan-id", default=None)
    seed.add_argument("--tables", nargs="*", default=None)
    seed.add_argument(
        "--yes-i-reviewed-the-plan",
        action="store_true",
        help="Non-interactive confirmation (CI/automation, use with care)",
    )
    seed.set_defaults(func=cmd_seed)

    sample = sub.add_parser(
        "sample-seed",
        help="Development sandbox only: run the real seed pipeline against "
        "the deterministic sample dataset (no Oracle needed)",
    )
    sample.add_argument("--tables", nargs="*", default=None)
    sample.add_argument("--skip-dbt", action="store_true")
    sample.set_defaults(func=cmd_sample_seed)

    sync = sub.add_parser("sync")
    sync.add_argument("--cadence", nargs="*", default=["hourly"])
    sync.add_argument("--tables", nargs="*", default=None)
    sync.set_defaults(func=cmd_sync)

    reconcile = sub.add_parser("reconcile-deletes")
    reconcile.add_argument("--tables", nargs="*", default=None)
    reconcile.set_defaults(func=cmd_reconcile_deletes)

    dbt = sub.add_parser("dbt")
    dbt.add_argument("--target", nargs="*", default=None)
    dbt.set_defaults(func=cmd_dbt)

    dispatch_parser = sub.add_parser("dispatch")
    dispatch_parser.add_argument("--no-dbt", action="store_true")
    dispatch_parser.set_defaults(func=cmd_dispatch)

    sub.add_parser("freshness").set_defaults(func=cmd_freshness)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
