"""Operator CLI: argument parsing and the interactive seed gate."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.dataplatform import cli
from app.dataplatform.pipeline import plans, state


@pytest.fixture(autouse=True)
def _stub_pipeline_lock(monkeypatch):
    """The writer commands take the single-flight lock (INC-013); offline
    tests stub it (no Postgres) while test_single_flight.py proves it."""

    @contextmanager
    def fake_lock(name: str = "smartforge_pipeline"):  # noqa: ARG001
        yield

    monkeypatch.setattr(state, "pipeline_lock", fake_lock)


def make_cli_plan(*, blocking: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        plan_id="plan_1",
        fingerprint=lambda: "abcd1234",
        tables=[
            SimpleNamespace(
                contract=SimpleNamespace(qualified_name="OMEGA.MACHINES"),
                estimated_rows=10,
                warnings=[],
            )
        ],
        blocking_issues=blocking or [],
    )


class TestArgumentParsing:
    def test_no_command_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc:
            cli.main([])
        assert exc.value.code == 2

    def test_unknown_command_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["frobnicate"])
        assert exc.value.code == 2

    def test_unknown_flag_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["seed", "--force"])
        assert exc.value.code == 2


class TestSeedGate:
    def _patch_confirm(self, monkeypatch):
        """Real gate semantics: only the exact phrase confirms."""
        attempts: list[str] = []

        def fake_confirm(_plan_id, _fingerprint, phrase, **_kwargs):
            attempts.append(phrase)
            if phrase != plans.CONFIRMATION_PHRASE:
                raise plans.PlanNotConfirmedError("Confirmation phrase mismatch.")
            return make_cli_plan()

        monkeypatch.setattr(plans, "confirm_plan", fake_confirm)
        return attempts

    def test_seed_without_flag_prompts_and_aborts_on_wrong_phrase(
        self, monkeypatch, capsys
    ):
        monkeypatch.setattr(plans, "latest_plan", lambda: make_cli_plan())
        attempts = self._patch_confirm(monkeypatch)
        prompts: list[str] = []
        monkeypatch.setattr(
            "builtins.input", lambda prompt="": prompts.append(prompt) or "no thanks"
        )

        import app.dataplatform.pipeline.full_seed as full_seed_module

        monkeypatch.setattr(
            full_seed_module,
            "run_full_seed",
            lambda *a, **k: pytest.fail("seed must not run without confirmation"),
        )
        rc = cli.main(["seed"])
        assert rc == 1
        assert attempts == ["no thanks"]
        assert prompts and "SEED OMEGA" in prompts[0]
        out = capsys.readouterr().out
        assert "phrase mismatch" in out

    def test_seed_aborts_in_noninteractive_mode(self, monkeypatch):
        # No TTY / closed stdin: input() raises EOFError and nothing seeds.
        monkeypatch.setattr(plans, "latest_plan", lambda: make_cli_plan())
        self._patch_confirm(monkeypatch)
        monkeypatch.setattr(
            "builtins.input",
            lambda prompt="": (_ for _ in ()).throw(EOFError()),
        )
        import app.dataplatform.pipeline.full_seed as full_seed_module

        monkeypatch.setattr(
            full_seed_module,
            "run_full_seed",
            lambda *a, **k: pytest.fail("seed must not run without confirmation"),
        )
        with pytest.raises(EOFError):
            cli.main(["seed"])

    def test_seed_with_review_flag_confirms_and_runs(self, monkeypatch, capsys):
        monkeypatch.setattr(plans, "latest_plan", lambda: make_cli_plan())
        attempts = self._patch_confirm(monkeypatch)
        monkeypatch.setattr(
            "builtins.input",
            lambda prompt="": pytest.fail("must not prompt with the review flag"),
        )
        executed: list[tuple] = []
        import app.dataplatform.pipeline.full_seed as full_seed_module

        monkeypatch.setattr(
            full_seed_module,
            "run_full_seed",
            lambda plan, tables=None: (
                executed.append(("run", tables)) or {"status": "succeeded"}
            ),
        )
        monkeypatch.setattr(
            plans,
            "mark_executed",
            lambda plan_id, result: executed.append(("mark", plan_id)),
        )
        rc = cli.main(["seed", "--yes-i-reviewed-the-plan"])
        assert rc == 0
        assert attempts == ["SEED OMEGA"]
        assert ("run", None) in executed
        assert ("mark", "plan_1") in executed

    def test_seed_with_blocking_issues_never_confirms(self, monkeypatch, capsys):
        monkeypatch.setattr(
            plans,
            "latest_plan",
            lambda: make_cli_plan(blocking=["unmapped type SDO_GEOMETRY"]),
        )
        monkeypatch.setattr(
            plans,
            "confirm_plan",
            lambda *a, **k: pytest.fail("blocked plan must not be confirmable"),
        )
        rc = cli.main(["seed", "--yes-i-reviewed-the-plan"])
        assert rc == 1
        assert "BLOCKING ISSUES" in capsys.readouterr().out

    def test_seed_without_any_plan(self, monkeypatch, capsys):
        monkeypatch.setattr(plans, "latest_plan", lambda: None)
        rc = cli.main(["seed"])
        assert rc == 1
        assert "no seed plan" in capsys.readouterr().out

    def test_seed_plan_id_mismatch(self, monkeypatch, capsys):
        monkeypatch.setattr(plans, "latest_plan", lambda: make_cli_plan())
        rc = cli.main(["seed", "--plan-id", "plan_other"])
        assert rc == 1
        assert "plan_1" in capsys.readouterr().out


class TestOtherCommands:
    def test_sync_exit_codes(self, monkeypatch, capsys):
        import app.dataplatform.pipeline.incremental as incremental_module

        monkeypatch.setattr(
            incremental_module,
            "run_incremental",
            lambda cadence, tables=None: {"run_id": "r", "synced": [], "failures": []},
        )
        assert cli.main(["sync"]) == 0

        monkeypatch.setattr(
            incremental_module,
            "run_incremental",
            lambda cadence, tables=None: {
                "run_id": "r",
                "synced": [],
                "failures": [{"table": "T", "error": "x"}],
            },
        )
        assert cli.main(["sync", "--cadence", "hourly", "daily"]) == 1
        capsys.readouterr()

    def test_freshness_exit_codes(self, monkeypatch, capsys):
        import app.dataplatform.pipeline.freshness as freshness_module

        monkeypatch.setattr(
            freshness_module,
            "table_freshness",
            lambda: [{"table": "OMEGA.MACHINES", "status": "fresh"}],
        )
        assert cli.main(["freshness"]) == 0

        monkeypatch.setattr(
            freshness_module,
            "table_freshness",
            lambda: [{"table": "OMEGA.MACHINES", "status": "stale"}],
        )
        assert cli.main(["freshness"]) == 1
        capsys.readouterr()

    def test_plan_command_without_plan(self, monkeypatch, capsys):
        monkeypatch.setattr(plans, "latest_plan", lambda: None)
        assert cli.main(["plan"]) == 1
        assert "no seed plan" in capsys.readouterr().out
