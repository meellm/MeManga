"""
Container-native scheduling (issue #327): ``memanga watch`` stays in the
foreground and runs ``check --auto --quiet`` at a fixed interval, so a
Compose service with a restart policy keeps checks going without a host
cron job.

Each check runs as a child process, the same command a cron entry runs.
It loads config and state fresh, takes the config directory lock only
while it works (issue #244), and saves state on SIGTERM (issue #230).
The watcher itself never loads or writes anything, so other commands can
change the library between checks. Checks never overlap: the next one
starts only after the previous one exited.
"""

import random
import re
import signal
import subprocess
import time

# Shortest allowed interval, so a typo cannot hammer the sources.
MIN_INTERVAL = 15 * 60

# Seconds a terminated check may take to save state before it is killed.
# Below compose.yaml's stop_grace_period (1m), after which Docker kills
# everything; `docker run` without --stop-timeout allows only 10 s.
STOP_TIMEOUT = 45

_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_DURATION = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")


def parse_duration(text) -> int:
    """Seconds in a duration such as ``6h``, ``1h30m``, ``90m`` or ``1d``.

    Units are d, h, m and s, in that order, each at most once. A bare
    number is refused because its unit would be a guess.
    """
    value = str(text).strip().lower()
    match = _DURATION.fullmatch(value)
    if not value or match is None:
        raise ValueError(
            f"invalid duration {text!r}: use a number with a unit, "
            "e.g. 6h, 90m or 1h30m")
    return sum(int(amount) * _UNITS[unit]
               for amount, unit in zip(match.groups(), "dhms") if amount)


def format_duration(seconds) -> str:
    """``21600`` -> ``6h``; ``5400`` -> ``1h30m``; ``0`` -> ``0s``."""
    seconds = int(round(seconds))
    parts = []
    for unit, size in _UNITS.items():
        amount, seconds = divmod(seconds, size)
        if amount:
            parts.append(f"{amount}{unit}")
    return "".join(parts) or "0s"


def build_check_argv(python_path, config_dir=None, verbose=0,
                     log_quiet=False, plain=False, log_file=False) -> list:
    """The child command for one scheduled check.

    Global output options are passed on so the check logs like the
    watcher was asked to.
    """
    argv = [str(python_path), "-m", "memanga"]
    if config_dir is not None:
        argv += ["--config-dir", str(config_dir)]
    if verbose:
        argv.append("-" + "v" * verbose)
    if log_quiet:
        argv.append("-q")
    if plain:
        argv.append("--plain")
    if log_file:
        argv.append("--log-file")
    argv += ["check", "--auto", "--quiet"]
    return argv


def _stop_child(proc, timeout):
    """Ask a running check to save and exit; kill it if it does not."""
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGTERM)
    except OSError:
        return  # already gone
    try:
        proc.wait(timeout=timeout)
    except BaseException:
        # Timed out, or a second interrupt: do not leave it running.
        proc.kill()
        proc.wait()
        raise


def run_check(argv, *, cwd=None, popen=subprocess.Popen,
              stop_timeout=STOP_TIMEOUT) -> int:
    """Run one check to completion and return its exit code.

    If the wait is interrupted (SIGTERM turned into an exception by the
    CLI, Ctrl-C), the check is stopped first and the exception re-raised,
    so the watcher never exits while a check is still writing state.
    The check gets its own session, so a terminal's Ctrl-C reaches only
    the watcher, which then sends the one SIGTERM; a second signal in
    the middle of the check's save could otherwise cut it short.
    """
    proc = popen(argv, cwd=cwd, start_new_session=True)
    try:
        return proc.wait()
    except BaseException:
        try:
            _stop_child(proc, stop_timeout)
        except subprocess.TimeoutExpired:
            pass  # killed; report the original interrupt
        raise


def run_watch(argv, every, jitter=0, *, cwd=None, report=None,
              popen=subprocess.Popen, sleep=time.sleep, clock=time.monotonic,
              rand=random.uniform, max_runs=None, stop_timeout=STOP_TIMEOUT):
    """Run ``argv`` now and then every ``every`` seconds plus up to
    ``jitter`` random seconds, start to start, until interrupted.

    A check that runs past its slot is never overlapped; the next one
    starts as soon as it exits. A failing check is reported and the
    schedule continues. ``report(event, **details)`` receives
    ``"start"``, ``"finished"`` (with ``code`` and ``elapsed``) and
    ``"waiting"`` (with ``delay``). ``max_runs`` stops after that many
    checks (for tests).
    """
    report = report or (lambda event, **details: None)
    runs = 0
    while True:
        started = clock()
        report("start")
        code = run_check(argv, cwd=cwd, popen=popen,
                         stop_timeout=stop_timeout)
        runs += 1
        report("finished", code=code, elapsed=clock() - started)
        if max_runs is not None and runs >= max_runs:
            return
        target = started + every + (rand(0, jitter) if jitter else 0)
        delay = max(0.0, target - clock())
        report("waiting", delay=delay)
        if delay:
            sleep(delay)
