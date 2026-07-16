"""Pipeline performance metrics (OBS-008): Prometheus instruments, the
run-level KPI block, and the one-line migration summary."""

from __future__ import annotations

import logging

import pytest

from app.dataplatform.metrics import (
    PIPELINE_REGISTRY,
    PipelineRunStats,
    format_bytes,
    megabits_per_second,
    stage_timer,
)


def sample(name: str, labels: dict[str, str]) -> float | None:
    return PIPELINE_REGISTRY.get_sample_value(name, labels)


class TestFormatting:
    def test_format_bytes_iec_units(self):
        assert format_bytes(512) == "512 B"
        assert format_bytes(2048) == "2.0 KiB"
        assert format_bytes(3.5 * 1024 * 1024) == "3.5 MiB"
        assert format_bytes(2 * 1024**3) == "2.0 GiB"

    def test_megabits_per_second(self):
        # 1_000_000 bytes over 8 seconds = 1 Mbps exactly.
        assert megabits_per_second(1_000_000, 8) == pytest.approx(1.0)
        assert megabits_per_second(1_000_000, 0) == 0.0


class TestStageTimer:
    def test_observes_duration(self):
        labels = {"table": "unit_test_table", "stage": "publish"}
        before = sample("smartforge_pipeline_stage_duration_seconds_count", labels) or 0
        with stage_timer("unit_test_table", "publish"):
            pass
        after = sample("smartforge_pipeline_stage_duration_seconds_count", labels)
        assert after == before + 1

    def test_failure_latency_is_still_recorded(self):
        labels = {"table": "unit_test_table", "stage": "warehouse_load"}
        before = sample("smartforge_pipeline_stage_duration_seconds_count", labels) or 0
        with pytest.raises(RuntimeError):
            with stage_timer("unit_test_table", "warehouse_load"):
                raise RuntimeError("boom")
        after = sample("smartforge_pipeline_stage_duration_seconds_count", labels)
        assert after == before + 1


class TestPipelineRunStats:
    def test_kpi_block_and_instruments(self, caplog):
        stats = PipelineRunStats("unit_seed", source="sample")
        stats.record_table("alpha", rows=100, size_bytes=1_000_000)
        stats.record_table("beta", rows=50, size_bytes=500_000)
        stats.record_table("gamma", succeeded=False)
        with caplog.at_level(logging.INFO, logger="app.dataplatform.metrics"):
            kpis = stats.finish()

        # The migration KPI block: "we migrated X from Y in Z seconds for
        # N rows and N tables — % success" in machine-readable form.
        assert kpis["kind"] == "unit_seed"
        assert kpis["source"] == "sample"
        assert kpis["tables_total"] == 3
        assert kpis["tables_succeeded"] == 2
        assert kpis["tables_failed"] == 1
        assert kpis["rows"] == 150
        assert kpis["bytes"] == 1_500_000
        assert kpis["bytes_human"] == "1.4 MiB"
        assert kpis["success_rate_percent"] == pytest.approx(66.7)
        # duration_seconds is rounded to ms; a sub-ms unit-test run rounds
        # to 0.0, so assert non-negative here and positivity via the rate.
        assert kpis["duration_seconds"] >= 0
        assert kpis["rows_per_second"] > 0
        assert kpis["throughput_megabits_per_second"] > 0
        assert kpis["started_at"] <= kpis["completed_at"]

        # Instruments: counters carry per-table totals; last-run gauges
        # carry the dashboard KPIs.
        assert (
            sample(
                "smartforge_pipeline_rows_total",
                {"table": "alpha", "kind": "unit_seed"},
            )
            == 100
        )
        assert (
            sample(
                "smartforge_pipeline_table_syncs_total",
                {"table": "gamma", "kind": "unit_seed", "status": "failed"},
            )
            == 1
        )
        assert (
            sample(
                "smartforge_pipeline_runs_total",
                {"kind": "unit_seed", "status": "failed"},
            )
            == 1
        )
        assert sample("smartforge_pipeline_last_run_rows", {"kind": "unit_seed"}) == 150
        assert sample(
            "smartforge_pipeline_last_run_success_ratio", {"kind": "unit_seed"}
        ) == pytest.approx(2 / 3)

        # Exactly one grep-able summary line, no data values in it.
        lines = [
            r.getMessage()
            for r in caplog.records
            if "pipeline unit_seed complete" in r.getMessage()
        ]
        assert len(lines) == 1
        assert "2/3 tables" in lines[0]
        assert "150 rows" in lines[0]
        assert "success 66.7%" in lines[0]
        assert "Mbps" in lines[0]

    def test_empty_run_is_full_success(self):
        kpis = PipelineRunStats("unit_noop").finish()
        assert kpis["tables_total"] == 0
        assert kpis["success_rate_percent"] == 100.0


class TestExposition:
    def test_api_metrics_endpoint_includes_pipeline_registry(self):
        from app.exporters.prometheus import render_metrics

        text = render_metrics().decode()
        assert "smartforge_machine_health_score" in text  # factory exporter
        assert "smartforge_pipeline_runs_total" in text  # pipeline registry
