"""Tests for memanga.perf - opt-in timing instrumentation.

Covers both usage forms (decorator and context manager), the
enabled/disabled gate, environment resolution, and the bounded
sample buffer.
"""

from __future__ import annotations

import pytest

from memanga import perf
from memanga.perf import timed


@pytest.fixture(autouse=True)
def clean_perf(monkeypatch):
    """Each test starts disabled with an empty buffer and no env leak."""
    monkeypatch.delenv("MEMANGA_PERF", raising=False)
    perf.set_enabled(None)
    perf.clear_samples()
    yield
    perf.set_enabled(None)
    perf.clear_samples()


class TestEnabledGate:
    def test_disabled_by_default(self):
        assert not perf.is_enabled()

    @pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
    def test_truthy_env_values_enable(self, monkeypatch, value):
        monkeypatch.setenv("MEMANGA_PERF", value)
        perf.set_enabled(None)
        assert perf.is_enabled()

    @pytest.mark.parametrize("value", ["", "0", "false", "off", "nope"])
    def test_other_env_values_stay_disabled(self, monkeypatch, value):
        monkeypatch.setenv("MEMANGA_PERF", value)
        perf.set_enabled(None)
        assert not perf.is_enabled()

    def test_set_enabled_overrides_env(self, monkeypatch):
        monkeypatch.setenv("MEMANGA_PERF", "1")
        perf.set_enabled(False)
        assert not perf.is_enabled()
        perf.set_enabled(True)
        assert perf.is_enabled()

    def test_disabled_records_nothing(self):
        with timed("quiet"):
            pass
        assert perf.recent_samples() == []


class TestTimedContextManager:
    def test_records_name_and_duration(self):
        perf.set_enabled(True)
        with timed("block"):
            pass
        samples = perf.recent_samples()
        assert len(samples) == 1
        name, duration_ms = samples[0]
        assert name == "block"
        assert duration_ms >= 0

    def test_records_even_when_body_raises(self):
        perf.set_enabled(True)
        with pytest.raises(ValueError):
            with timed("boom"):
                raise ValueError("bad")
        assert perf.recent_samples()[0][0] == "boom"


class TestTimedDecorator:
    def test_preserves_return_value_and_name(self):
        perf.set_enabled(True)

        @timed("fn")
        def add(a, b=1):
            return a + b

        assert add(2, b=3) == 5
        assert add.__name__ == "add"
        assert perf.recent_samples()[0][0] == "fn"

    def test_reusable_across_calls(self):
        # A generator-based context manager is single-use; the decorator
        # form must recreate it per call.
        perf.set_enabled(True)

        @timed("fn")
        def noop():
            pass

        noop()
        noop()
        assert [n for n, _ in perf.recent_samples()] == ["fn", "fn"]

    def test_enabled_checked_at_call_time(self):
        # Decorators are applied at import time, before tests (or the
        # user) flip the switch - the gate must not be baked in.
        @timed("late")
        def noop():
            pass

        noop()
        assert perf.recent_samples() == []
        perf.set_enabled(True)
        noop()
        assert [n for n, _ in perf.recent_samples()] == ["late"]

    def test_decorated_state_save_records_sample(self, state):
        # Integration: State.save carries @timed("state.save").
        perf.set_enabled(True)
        state.save()
        assert "state.save" in [n for n, _ in perf.recent_samples()]

    def test_decorated_config_save_records_sample(self, config):
        perf.set_enabled(True)
        config.save()
        assert "config.save" in [n for n, _ in perf.recent_samples()]


class TestSampleBuffer:
    def test_clear_samples(self):
        perf.set_enabled(True)
        with timed("x"):
            pass
        perf.clear_samples()
        assert perf.recent_samples() == []

    def test_buffer_is_bounded(self):
        perf.set_enabled(True)
        for i in range(perf._MAX_SAMPLES + 50):
            with timed(f"s{i}"):
                pass
        samples = perf.recent_samples()
        assert len(samples) == perf._MAX_SAMPLES
        # Oldest entries were dropped, newest kept.
        assert samples[-1][0] == f"s{perf._MAX_SAMPLES + 49}"

    def test_snapshot_safe_under_concurrent_appends(self):
        # Without the lock, list(_samples) can raise "deque mutated
        # during iteration" while a worker thread appends.
        import threading

        perf.set_enabled(True)
        stop = threading.Event()

        def writer():
            while not stop.is_set():
                with timed("w"):
                    pass

        threads = [threading.Thread(target=writer) for _ in range(2)]
        for t in threads:
            t.start()
        try:
            for _ in range(500):
                snapshot = perf.recent_samples()
                assert all(name == "w" for name, _ in snapshot)
        finally:
            stop.set()
            for t in threads:
                t.join()
