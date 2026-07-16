"""Freshness classification boundaries using real PlatformSettings defaults."""

from __future__ import annotations

import datetime as dt

import pytest

from app.dataplatform.pipeline import freshness
from app.dataplatform.registry import Cadence, Registry
from tests_dataplatform.conftest import FakeEngine, FakeResult


@pytest.fixture
def two_table_registry(registry) -> Registry:
    return Registry(
        contracts={
            "OMEGA.WORK_ORDERS": registry.get("OMEGA.WORK_ORDERS"),  # hourly
            "OMEGA.MACHINES": registry.get("OMEGA.MACHINES"),  # daily
        }
    )


def _report_with_lag(
    monkeypatch, two_table_registry, *, hourly_lag_min=None, daily_lag_min=None
):
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    if hourly_lag_min is not None:
        rows.append(
            (
                "OMEGA",
                "WORK_ORDERS",
                "cv",
                100,
                "load_h",
                now - dt.timedelta(minutes=hourly_lag_min),
            )
        )
    if daily_lag_min is not None:
        rows.append(
            (
                "OMEGA",
                "MACHINES",
                "cv",
                200,
                "load_d",
                now - dt.timedelta(minutes=daily_lag_min),
            )
        )
    engine = FakeEngine(lambda sql, params: FakeResult(rows=rows))
    monkeypatch.setattr(freshness, "api_engine", lambda: engine)
    report = freshness.table_freshness(two_table_registry)
    return {r["table"]: r for r in report}


class TestThresholds:
    def test_real_settings_defaults_drive_thresholds(self, platform_env):
        assert freshness._thresholds(Cadence.hourly) == (75, 120)
        assert freshness._thresholds(Cadence.daily) == (1560, 1800)
        assert freshness._thresholds(Cadence.weekly) == (60 * 24 * 8, 60 * 24 * 10)


class TestHourlyBoundaries:
    @pytest.mark.parametrize(
        ("lag", "expected"),
        [
            (10, "fresh"),
            (74, "fresh"),  # just under warn (75)
            (76, "warning"),  # just over warn
            (119, "warning"),  # just under error (120)
            (121, "stale"),  # just over error
            (60 * 24, "stale"),
        ],
    )
    def test_hourly_status(
        self, monkeypatch, platform_env, two_table_registry, lag, expected
    ):
        report = _report_with_lag(
            monkeypatch, two_table_registry, hourly_lag_min=lag, daily_lag_min=1
        )
        assert report["OMEGA.WORK_ORDERS"]["status"] == expected
        assert report["OMEGA.WORK_ORDERS"]["cadence"] == "hourly"


class TestDailyBoundaries:
    @pytest.mark.parametrize(
        ("lag", "expected"),
        [
            (60 * 12, "fresh"),
            (1559, "fresh"),  # just under warn (26 h)
            (1561, "warning"),  # just over warn
            (1799, "warning"),  # just under error (30 h)
            (1801, "stale"),  # just over error
        ],
    )
    def test_daily_status(
        self, monkeypatch, platform_env, two_table_registry, lag, expected
    ):
        report = _report_with_lag(
            monkeypatch, two_table_registry, hourly_lag_min=1, daily_lag_min=lag
        )
        assert report["OMEGA.MACHINES"]["status"] == expected


class TestNeverLoaded:
    def test_missing_watermark_row_reports_never_loaded(
        self, monkeypatch, platform_env, two_table_registry
    ):
        report = _report_with_lag(monkeypatch, two_table_registry, hourly_lag_min=5)
        machines = report["OMEGA.MACHINES"]
        assert machines["status"] == "never_loaded"
        assert machines["lag_minutes"] is None
        assert machines["last_load_id"] is None

    def test_report_carries_provenance_fields(
        self, monkeypatch, platform_env, two_table_registry
    ):
        report = _report_with_lag(
            monkeypatch, two_table_registry, hourly_lag_min=5, daily_lag_min=5
        )
        wo = report["OMEGA.WORK_ORDERS"]
        assert wo["last_load_id"] == "load_h"
        assert wo["source_scn"] == 100
        assert wo["destination"] == "work_orders"
        assert wo["last_published_at"] is not None

    def test_naive_updated_at_is_treated_as_utc(
        self, monkeypatch, platform_env, two_table_registry
    ):
        now_naive = dt.datetime.now(dt.timezone.utc).replace(
            tzinfo=None
        ) - dt.timedelta(minutes=5)
        rows = [
            ("OMEGA", "WORK_ORDERS", "cv", 100, "load_h", now_naive),
            ("OMEGA", "MACHINES", "cv", 200, "load_d", now_naive),
        ]
        engine = FakeEngine(lambda sql, params: FakeResult(rows=rows))
        monkeypatch.setattr(freshness, "api_engine", lambda: engine)
        report = {r["table"]: r for r in freshness.table_freshness(two_table_registry)}
        assert report["OMEGA.WORK_ORDERS"]["status"] == "fresh"
