"""Tests for memanga.watch, the interval scheduler behind `memanga watch` (#327)."""

import signal
import subprocess

import pytest

from memanga import watch


class TestParseDuration:
    @pytest.mark.parametrize("text, seconds", [
        ("6h", 6 * 3600),
        ("90m", 90 * 60),
        ("1h30m", 5400),
        ("1d", 86400),
        ("45s", 45),
        ("1d2h3m4s", 86400 + 7200 + 180 + 4),
        (" 6H ", 6 * 3600),
        ("0s", 0),
    ])
    def test_valid(self, text, seconds):
        assert watch.parse_duration(text) == seconds

    @pytest.mark.parametrize("text", [
        "", "6", "h", "6x", "-1h", "1.5h", "30m1h", "1h1h", "6 h", "six hours",
    ])
    def test_invalid(self, text):
        with pytest.raises(ValueError, match="invalid duration"):
            watch.parse_duration(text)

    @pytest.mark.parametrize("seconds, text", [
        (21600, "6h"), (5400, "1h30m"), (0, "0s"), (90061, "1d1h1m1s"),
        (59.6, "1m"),
    ])
    def test_format(self, seconds, text):
        assert watch.format_duration(seconds) == text


class TestBuildCheckArgv:
    def test_default(self):
        assert watch.build_check_argv("/py") == [
            "/py", "-m", "memanga", "check", "--auto", "--quiet"]

    def test_global_options_go_before_the_command(self):
        argv = watch.build_check_argv("/py", "/cfg", verbose=2, plain=True,
                                      log_file=True)
        assert argv == ["/py", "-m", "memanga", "--config-dir", "/cfg", "-vv",
                        "--plain", "--log-file", "check", "--auto", "--quiet"]

    def test_quiet(self):
        argv = watch.build_check_argv("/py", log_quiet=True)
        assert argv[3:] == ["-q", "check", "--auto", "--quiet"]


class FakeProc:
    """A child process whose wait() can run a callback (a signal)."""

    def __init__(self, code=0, on_wait=None):
        self.code = code
        self.on_wait = on_wait
        self.returncode = None
        self.signals = []
        self.killed = False
        self.waits = []

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.on_wait is not None:
            callback, self.on_wait = self.on_wait, None
            callback(self)
        self.returncode = self.code
        return self.code

    def send_signal(self, signum):
        self.signals.append(signum)

    def kill(self):
        self.killed = True
        self.returncode = -9


class Harness:
    """Fake clock, sleep and Popen for run_watch."""

    def __init__(self, procs, durations=None):
        self.now = 1000.0
        self.procs = list(procs)
        self.durations = list(durations or [])
        self.started = []
        self.sleeps = []
        self.calls = []
        self.events = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def popen(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        self.started.append(self.now)
        if self.durations:
            self.now += self.durations.pop(0)
        return self.procs.pop(0)

    def report(self, event, **details):
        self.events.append((event, details))

    def run(self, every=3600, jitter=0, max_runs=None, rand=None, **kwargs):
        return watch.run_watch(
            ["memanga", "check"], every, jitter, cwd="/src",
            report=self.report, popen=self.popen, sleep=self.sleep,
            clock=self.clock, rand=rand or (lambda a, b: b),
            max_runs=max_runs, **kwargs)


class TestRunWatch:
    def test_runs_now_then_every_interval_start_to_start(self):
        h = Harness([FakeProc(), FakeProc(), FakeProc()], durations=[600, 60, 0])
        h.run(every=3600, max_runs=3)
        assert h.started == [1000.0, 4600.0, 8200.0]
        assert h.sleeps == [3000.0, 3540.0]

    def test_child_gets_cwd_and_its_own_session(self):
        h = Harness([FakeProc()])
        h.run(max_runs=1)
        argv, kwargs = h.calls[0]
        assert argv == ["memanga", "check"]
        assert kwargs == {"cwd": "/src", "start_new_session": True}

    def test_jitter_is_added_to_each_wait(self):
        seen = []

        def rand(low, high):
            seen.append((low, high))
            return 120
        h = Harness([FakeProc(), FakeProc()])
        h.run(every=3600, jitter=1800, max_runs=2, rand=rand)
        assert seen == [(0, 1800)]
        assert h.sleeps == [3720.0]

    def test_no_jitter_draws_no_random_number(self):
        def rand(low, high):
            raise AssertionError("rand called without jitter")
        h = Harness([FakeProc(), FakeProc()])
        h.run(every=3600, max_runs=2, rand=rand)
        assert h.sleeps == [3600.0]

    def test_long_check_is_not_overlapped(self):
        h = Harness([FakeProc(), FakeProc()], durations=[5000, 0])
        h.run(every=3600, max_runs=2)
        # The next check starts as soon as the late one ended.
        assert h.started == [1000.0, 6000.0]
        assert h.sleeps == []
        assert ("waiting", {"delay": 0.0}) in h.events

    def test_failed_check_is_reported_and_schedule_continues(self):
        h = Harness([FakeProc(code=1), FakeProc(code=3), FakeProc()],
                    durations=[10, 20, 30])
        h.run(max_runs=3)
        finished = [d for e, d in h.events if e == "finished"]
        assert [d["code"] for d in finished] == [1, 3, 0]
        assert [d["elapsed"] for d in finished] == [10, 20, 30]
        assert len(h.started) == 3

    def test_events_in_order(self):
        h = Harness([FakeProc(), FakeProc()])
        h.run(every=3600, max_runs=2)
        assert [e for e, _ in h.events] == [
            "start", "finished", "waiting", "start", "finished"]

    def test_interrupt_while_idle_propagates_without_a_child(self):
        class Stop(BaseException):
            pass
        h = Harness([FakeProc()])

        def sleep(seconds):
            raise Stop()
        h.sleep = sleep
        with pytest.raises(Stop):
            h.run(max_runs=None)
        assert len(h.calls) == 1


class Stop(BaseException):
    """Stands in for the CLI's TerminationRequested."""


class TestRunCheckInterrupted:
    def _interrupted_once(self, proc):
        raise Stop()

    def test_sigterm_is_forwarded_and_child_awaited(self):
        proc = FakeProc(code=143, on_wait=self._interrupted_once)
        with pytest.raises(Stop):
            watch.run_check(["x"], popen=lambda argv, **kw: proc,
                            stop_timeout=5)
        assert proc.signals == [signal.SIGTERM]
        assert proc.waits == [None, 5]
        assert not proc.killed

    def test_keyboard_interrupt_also_stops_the_child(self):
        def ctrl_c(proc):
            raise KeyboardInterrupt
        proc = FakeProc(code=143, on_wait=ctrl_c)
        with pytest.raises(KeyboardInterrupt):
            watch.run_check(["x"], popen=lambda argv, **kw: proc)
        assert proc.signals == [signal.SIGTERM]

    def test_child_that_does_not_stop_is_killed(self):
        class Stuck(FakeProc):
            def wait(self, timeout=None):
                self.waits.append(timeout)
                if len(self.waits) == 1:
                    raise Stop()
                if timeout is not None:
                    raise subprocess.TimeoutExpired("x", timeout)
                return self.returncode
        proc = Stuck()
        with pytest.raises(Stop):
            watch.run_check(["x"], popen=lambda argv, **kw: proc,
                            stop_timeout=5)
        assert proc.signals == [signal.SIGTERM]
        assert proc.killed

    def test_second_interrupt_kills_the_child(self):
        class Twice(FakeProc):
            def wait(self, timeout=None):
                self.waits.append(timeout)
                if len(self.waits) <= 2:
                    raise Stop()
                return self.returncode
        proc = Twice()
        with pytest.raises(Stop):
            watch.run_check(["x"], popen=lambda argv, **kw: proc)
        assert proc.killed

    def test_child_already_gone_is_not_signalled(self):
        def exited_then_interrupted(proc):
            proc.returncode = 0
            raise Stop()
        proc = FakeProc(on_wait=exited_then_interrupted)
        with pytest.raises(Stop):
            watch.run_check(["x"], popen=lambda argv, **kw: proc)
        assert proc.signals == []

    def test_interrupt_during_watch_stops_the_running_check(self):
        proc = FakeProc(code=143, on_wait=self._interrupted_once)
        h = Harness([proc])
        with pytest.raises(Stop):
            h.run(max_runs=None)
        assert proc.signals == [signal.SIGTERM]
        assert [e for e, _ in h.events] == ["start"]
