"""Runtime observability plumbing: logging setup, crypto degradation
logging, and telemetry-simulator failure backoff (OBS-004/OBS-006).

All offline — no services, no sleeping (delays are recorded, not slept).
"""

import asyncio
import logging

import pytest

import app.workers.telemetry_simulator as sim_mod
from app.core import crypto
from app.core.config import settings
from app.core.logging_config import LOG_FORMAT, setup_logging

_NOISY = ("httpx", "httpcore", "urllib3")


@pytest.fixture(autouse=True)
def _restore_root_logging():
    """setup_logging(force=True) replaces root handlers; put everything back
    so pytest's own capture handlers survive the rest of the session."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_noisy = {name: logging.getLogger(name).level for name in _NOISY}
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    for name, level in saved_noisy.items():
        logging.getLogger(name).setLevel(level)


class TestSetupLogging:
    def test_default_root_level_and_format(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        setup_logging()
        root = logging.getLogger()
        assert root.level == logging.INFO
        assert root.handlers, "basicConfig must install a root handler"
        fmt = root.handlers[0].formatter._fmt  # noqa: SLF001 - asserting config
        assert "%(asctime)s" in fmt
        assert "%(name)s" in fmt
        assert fmt == LOG_FORMAT

    def test_log_level_env_honored(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        setup_logging()
        assert logging.getLogger().level == logging.DEBUG

    def test_invalid_log_level_falls_back_to_info(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
        setup_logging()
        assert logging.getLogger().level == logging.INFO

    def test_explicit_level_argument_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        setup_logging(level="ERROR")
        assert logging.getLogger().level == logging.ERROR

    def test_noisy_third_party_loggers_stay_at_warning(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        setup_logging()
        for name in _NOISY:
            assert logging.getLogger(name).level >= logging.WARNING


class TestCryptoDegradation:
    def test_valid_roundtrip_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.core.crypto"):
            assert crypto.decrypt(crypto.encrypt("shift notes")) == "shift notes"
        assert not caplog.records

    def test_corrupted_ciphertext_returns_stored_value_and_warns(self, caplog):
        corrupted = "enc::this-is-not-valid-fernet"
        with caplog.at_level(logging.WARNING, logger="app.core.crypto"):
            assert crypto.decrypt(corrupted) == corrupted
        warnings = [r for r in caplog.records if "decrypt failed" in r.getMessage()]
        assert len(warnings) == 1

    def test_legacy_plaintext_passthrough_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.core.crypto"):
            assert crypto.decrypt("plain old text") == "plain old text"
        assert not caplog.records


class _StopLoop(Exception):
    pass


class TestSimulatorBackoff:
    def test_backoff_grows_caps_and_resets_after_success(self, monkeypatch):
        """Failing ticks back off exponentially (capped at 60s); one success
        resets the cadence to the configured interval."""
        monkeypatch.setattr(settings, "SIMULATOR_INTERVAL_SECONDS", 3.0)

        # Ticks: 6 failures -> 1 success -> 1 failure.
        outcomes = iter([False] * 6 + [True, False])

        async def fake_tick():
            if not next(outcomes):
                raise RuntimeError("db unavailable")

        delays: list[float] = []

        async def fake_sleep(delay):
            delays.append(delay)
            if len(delays) >= 8:
                raise _StopLoop

        monkeypatch.setattr(sim_mod, "_tick", fake_tick)
        monkeypatch.setattr(sim_mod.asyncio, "sleep", fake_sleep)

        with pytest.raises(_StopLoop):
            asyncio.run(sim_mod.run_forever())

        # interval * 2^n, capped at 60s while failing...
        assert delays[:6] == [6.0, 12.0, 24.0, 48.0, 60.0, 60.0]
        # ...back to the plain interval after a success...
        assert delays[6] == 3.0
        # ...and the failure counter restarted (not resumed at the cap).
        assert delays[7] == 6.0
