"""Tests for memanga.cron shell-safe crontab line construction (#109)."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

import memanga

import memanga.cron as cron_mod
from memanga.cron import (
    MANAGED_MARKER,
    SCHEDULER_TIMEOUT,
    WINDOWS_TASK_NAME,
    ScheduleStatus,
    build_cron_line,
    build_task_command,
    install_schedule,
    is_managed_line,
    managed_lines,
    parse_schedule_time,
    quote_cron_path,
    read_crontab,
    remove_managed_lines,
    remove_schedule,
    replace_managed_line,
    schedule_status,
    scheduled_checks_supported,
    source_checkout_root,
    unmanaged_memanga_lines,
)


class TestQuoteCronPath:
    def test_plain_path_unchanged(self):
        assert quote_cron_path("/opt/memanga") == "/opt/memanga"

    def test_path_with_spaces_is_quoted(self):
        assert quote_cron_path("/opt/My Manga") == "'/opt/My Manga'"

    def test_shell_metacharacters_neutralized(self):
        evil = "/tmp/$(touch pwned); echo"
        assert shlex.split(quote_cron_path(evil)) == [evil]

    def test_percent_escaped_for_cron(self):
        # crontab(5) turns an unescaped % into a newline.
        assert quote_cron_path("/opt/100%manga") == r"/opt/100\%manga"


class TestBuildCronLine:
    def test_plain_paths(self):
        line = build_cron_line(0, 6, "/opt/memanga", "/usr/bin/python3")
        assert line == (
            "0 6 * * * cd /opt/memanga && /usr/bin/python3 "
            "-m memanga check --auto --quiet >> /opt/memanga/memanga.log 2>&1 "
            "# memanga-managed"
        )

    def test_paths_with_spaces(self):
        line = build_cron_line(30, 7, "/data/My Manga/.config/memanga",
                               "/opt/pipx venvs/my manga/bin/python")
        assert line == (
            "30 7 * * * cd '/data/My Manga/.config/memanga' && "
            "'/opt/pipx venvs/my manga/bin/python' "
            "-m memanga check --auto --quiet "
            ">> '/data/My Manga/.config/memanga/memanga.log' 2>&1 "
            "# memanga-managed"
        )

    def test_runs_interpreter_from_runtime_dir(self):
        """#232: the interpreter and the runtime dir are independent, so an
        installed interpreter never makes the job cd or log beside it."""
        line = build_cron_line(0, 6, "/data/.config/memanga",
                               "/opt/pipx/venvs/memanga/bin/python")
        command = shlex.split(line.split("* * * ", 1)[1], comments=True)
        assert command == [
            "cd", "/data/.config/memanga", "&&",
            "/opt/pipx/venvs/memanga/bin/python",
            "-m", "memanga", "check", "--auto", "--quiet",
            ">>", "/data/.config/memanga/memanga.log", "2>&1",
        ]

    def test_config_dir_is_passed_to_scheduled_check(self):
        line = build_cron_line(0, 6, "/opt/memanga", "/usr/bin/python3",
                               config_dir="/srv/My Manga/config")
        command = line.split("* * * ", 1)[1]
        assert shlex.split(command)[3:9] == [
            "/usr/bin/python3", "-m", "memanga",
            "--config-dir", "/srv/My Manga/config", "check",
        ]

    def test_metacharacter_paths_stay_single_words(self):
        evil = "/tmp/x; touch pwned"
        line = build_cron_line(0, 6, evil, "/usr/bin/python3")
        command = line.split("* * * ", 1)[1]
        # The shell must see the whole path as one word, not extra commands.
        assert evil in shlex.split(command)

    def test_marker_is_a_shell_comment(self):
        """The marker must not reach the scheduled command (#231)."""
        line = build_cron_line(0, 6, "/opt/memanga", "/usr/bin/python3")
        command = line.split("* * * ", 1)[1]
        assert shlex.split(command, comments=True)[-1] == "2>&1"
        assert line.endswith(" " + MANAGED_MARKER)


class TestSourceCheckoutRoot:
    """#232: which import root needs handling in the scheduled command."""

    def test_source_checkout(self, tmp_path):
        assert source_checkout_root(tmp_path / "My Checkout" / "memanga") == (
            tmp_path / "My Checkout")

    def test_installed_packages(self, tmp_path):
        for site in ("lib/python3.12/site-packages", "Lib/site-packages",
                     "lib/python3/dist-packages"):
            assert source_checkout_root(tmp_path / site / "memanga") is None

    def test_frozen_build(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert source_checkout_root(tmp_path / "memanga") is None

    def test_default_is_this_package(self):
        root = Path(memanga.__file__).resolve().parent.parent
        expected = None if root.name.endswith("-packages") else root
        assert source_checkout_root() == expected


class TestScheduledChecksSupported:
    """#324, #336: a frozen desktop build cannot run `-m memanga check`."""

    def test_source_or_installed(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert scheduled_checks_supported() is True

    def test_frozen_build(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert scheduled_checks_supported() is False


class TestSourceCheckoutCronLine:
    """#232: a requirements-only checkout venv cannot import memanga from
    an arbitrary cwd, so the job runs from the source root but still logs
    to the config root."""

    def test_runs_from_source_root_logs_to_runtime_dir(self):
        line = build_cron_line(0, 6, "/data/.config/memanga",
                               "/src/My Manga/venv/bin/python3",
                               source_root="/src/My Manga")
        command = shlex.split(line.split("* * * ", 1)[1], comments=True)
        assert command == [
            "cd", "/src/My Manga", "&&",
            "/src/My Manga/venv/bin/python3",
            "-m", "memanga", "check", "--auto", "--quiet",
            ">>", "/data/.config/memanga/memanga.log", "2>&1",
        ]

    def test_generated_command_imports_memanga_from_other_cwd(self, tmp_path):
        """Execute the generated shell command (check swapped for --help)
        from an unrelated cwd with a clean env: memanga must import and the
        output must land in the runtime dir's log."""
        root = source_checkout_root()
        if root is None:
            pytest.skip("memanga is installed, not a source checkout")
        runtime = tmp_path / "cfg dir"
        runtime.mkdir()
        line = build_cron_line(0, 6, runtime, sys.executable,
                               source_root=root)
        command = line.split("* * * ", 1)[1].replace(
            "check --auto --quiet", "--help")
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(tmp_path)}
        result = subprocess.run(["/bin/sh", "-c", command], cwd=tmp_path,
                                env=env, timeout=120)
        assert result.returncode == 0
        log = (runtime / "memanga.log").read_text()
        assert "No module named" not in log
        assert "cron" in log


def _argv_w(line):
    """Split a command line like ``CommandLineToArgvW`` / the MSVC CRT."""
    args, cur, i, quoted, have = [], [], 0, False, False
    while i < len(line):
        c = line[i]
        if c == "\\":
            n = 0
            while i < len(line) and line[i] == "\\":
                n, i = n + 1, i + 1
            if i < len(line) and line[i] == '"':
                cur.append("\\" * (n // 2))
                if n % 2:
                    cur.append('"')
                    i += 1
            else:
                cur.append("\\" * n)
            have = True
            continue
        if c == '"':
            if quoted and line[i + 1:i + 2] == '"':
                cur.append('"')
                i += 1
            else:
                quoted = not quoted
            have = True
        elif c in " \t" and not quoted:
            if have:
                args.append("".join(cur))
            cur, have = [], False
        else:
            cur.append(c)
            have = True
        i += 1
    if have:
        args.append("".join(cur))
    return args


def _run_task(tr):
    """What Windows ends up running for a ``schtasks /tr`` value.

    Layers: subprocess -> schtasks argv (list2cmdline + CRT parsing),
    Task Scheduler program/arguments split, then for ``cmd /c`` the
    documented strip-first-and-last-quote rule and ``&&`` chaining.
    Returns a list of argv lists, one per chained command.
    """
    argv = _argv_w(subprocess.list2cmdline(["schtasks", "/create", "/tr", tr]))
    stored = argv[argv.index("/tr") + 1]
    assert stored == tr
    if not stored.startswith("cmd /d /c "):
        return [_argv_w(stored)]
    body = stored[len("cmd /d /c "):]
    assert body.startswith('"') and body.endswith('"')
    body = body[1:-1]  # cmd /? : remove first and last quote only
    parts, cur, quoted = [], "", False
    i = 0
    while i < len(body):
        if body[i] == '"':
            quoted = not quoted
        if not quoted and body.startswith("&&", i):
            parts.append(cur)
            cur, i = "", i + 2
            continue
        cur += body[i]
        i += 1
    parts.append(cur)
    return [_argv_w(p) for p in parts]


class TestBuildTaskCommand:
    """Windows Task Scheduler command (#232), checked by how Windows
    parses it rather than by string shape alone."""

    CHECK = ["-m", "memanga", "check", "--auto", "--quiet"]

    def test_installed_runs_given_interpreter(self):
        python = r"C:\Program Files\Python312\python.exe"
        tr = build_task_command(python)
        assert tr == f'"{python}" -m memanga check --auto --quiet'
        assert _run_task(tr) == [[python, *self.CHECK]]

    def test_installed_config_dir_with_spaces(self):
        python = r"C:\Tools Dir\pipx\venvs\memanga\Scripts\python.exe"
        tr = build_task_command(python, r"D:\My Manga")
        assert tr == (f'"{python}" -m memanga --config-dir "D:\\My Manga" '
                      "check --auto --quiet")
        assert _run_task(tr) == [[python, "-m", "memanga", "--config-dir",
                                  r"D:\My Manga", "check", "--auto",
                                  "--quiet"]]

    def test_drive_root_config_dir_does_not_eat_quote(self):
        python = r"C:\Python312\python.exe"
        tr = build_task_command(python, "D:\\")
        assert _run_task(tr) == [[python, "-m", "memanga", "--config-dir",
                                  "D:\\", "check", "--auto", "--quiet"]]

    def test_source_checkout_with_spaces_changes_dir_first(self):
        root = r"C:\My R&D Manga"
        python = root + r"\venv\Scripts\python.exe"
        tr = build_task_command(python, r"D:\My Manga cfg", source_root=root)
        assert tr == (
            f'cmd /d /c "cd /d "{root}" && "{python}" -m memanga '
            '--config-dir "D:\\My Manga cfg" check --auto --quiet"')
        assert _run_task(tr) == [
            ["cd", "/d", root],
            [python, "-m", "memanga", "--config-dir", r"D:\My Manga cfg",
             "check", "--auto", "--quiet"],
        ]


MANAGED = build_cron_line(0, 6, "/opt/memanga", "/usr/bin/python3")
LEGACY = ("0 6 * * * cd /opt/memanga && /usr/bin/python3 -m memanga check "
          "--auto --quiet >> /opt/memanga/memanga.log 2>&1")
DOCKER = "0 5 * * * docker compose -f /srv/memanga/compose.yaml run --rm memanga check"
CRONTAB = (
    "# backups\n"
    "MAILTO=me@example.com\n"
    "\n"
    "30 2 * * *  /usr/local/bin/backup.sh   # nightly\n"
    f"{LEGACY}\n"
    "\n"
    f"{DOCKER}\n"
)


class TestManagedLines:
    """#231: only the marked line belongs to `cron install`."""

    def test_detection(self):
        assert is_managed_line(MANAGED)
        assert is_managed_line(MANAGED + "\n")
        assert not is_managed_line(LEGACY)
        assert not is_managed_line(DOCKER)
        assert not is_managed_line("# " + MANAGED)
        assert not is_managed_line("")

    def test_managed_lines(self):
        assert managed_lines(CRONTAB) == []
        assert managed_lines(CRONTAB + MANAGED + "\n") == [MANAGED]

    def test_unmanaged_memanga_lines(self):
        assert unmanaged_memanga_lines(CRONTAB + MANAGED + "\n") == [LEGACY, DOCKER]

    def test_remove_keeps_everything_else_byte_for_byte(self):
        text = CRONTAB.replace("\n\n", f"\n{MANAGED}\n\n", 1)
        new, removed = remove_managed_lines(text)
        assert removed == 1
        assert new == CRONTAB

    def test_remove_without_managed_line_is_a_no_op(self):
        assert remove_managed_lines(CRONTAB) == (CRONTAB, 0)
        assert remove_managed_lines("") == ("", 0)

    def test_replace_appends_to_untouched_crontab(self):
        assert replace_managed_line(CRONTAB, MANAGED) == CRONTAB + MANAGED + "\n"

    def test_replace_swaps_previous_managed_line(self):
        old = build_cron_line(15, 3, "/opt/memanga", "/usr/bin/python3")
        new = replace_managed_line(f"{old}\n{CRONTAB}{old}\n", MANAGED)
        assert new == CRONTAB + MANAGED + "\n"

    def test_replace_handles_missing_trailing_newline(self):
        assert replace_managed_line("", MANAGED) == MANAGED + "\n"
        assert replace_managed_line(DOCKER, MANAGED) == f"{DOCKER}\n{MANAGED}\n"


class TestReadCrontab:
    """#231: only a real "no crontab" failure counts as an empty crontab."""

    @staticmethod
    def _result(returncode, stdout="", stderr=""):
        return subprocess.CompletedProcess(["crontab", "-l"], returncode,
                                           stdout, stderr)

    def test_success_returns_text(self):
        assert read_crontab(self._result(0, CRONTAB)) == CRONTAB

    def test_no_crontab_is_empty(self):
        for err in ("no crontab for alice\n",
                    "crontab: no crontab for alice\n",
                    "crontab: can't open 'alice': No such file or directory\n"):
            assert read_crontab(self._result(1, stderr=err)) == ""

    def test_other_failures_are_unreadable(self):
        assert read_crontab(self._result(1)) is None
        assert read_crontab(self._result(
            1, stderr="crontab: Permission denied\n")) is None


class TestParseScheduleTime:
    @pytest.mark.parametrize("text, expected", [
        ("06:00", (6, 0)), ("6:5", (6, 5)), (" 23:59 ", (23, 59)),
        ("00:00", (0, 0)),
    ])
    def test_valid(self, text, expected):
        assert parse_schedule_time(text) == expected

    @pytest.mark.parametrize("text", [
        "24:00", "06:60", "-1:00", "6", "6:00:00", "aa:bb", "", "6:",
    ])
    def test_invalid(self, text):
        assert parse_schedule_time(text) is None


class FakeScheduler:
    """Stands in for ``subprocess.run`` so the service never touches a
    real crontab or Task Scheduler (issue #297)."""

    def __init__(self, crontab=None, read_rc=None, read_err="",
                 write_rc=0, results=None, error=None):
        if read_rc is None:
            read_rc = 0 if crontab is not None else 1
            if crontab is None:
                read_err = "no crontab for tester\n"
        self.crontab = crontab or ""
        self.read_rc, self.read_err = read_rc, read_err
        self.write_rc = write_rc
        self.results = results or {}
        self.error = error
        self.calls = []
        self.written = None
        self.deleted = False

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.error is not None:
            raise self.error
        if argv == ["crontab", "-l"]:
            return subprocess.CompletedProcess(argv, self.read_rc, self.crontab,
                                               self.read_err)
        if argv == ["crontab", "-"]:
            self.written = kwargs["input"]
            return subprocess.CompletedProcess(argv, self.write_rc, "", "denied")
        if argv == ["crontab", "-r"]:
            self.deleted = True
            return subprocess.CompletedProcess(argv, self.write_rc, "", "denied")
        # "/query /tn" (by name) and "/query /fo" (task list) can be told
        # apart; a plain "/query" key answers both.
        rc, out = self.results.get(" ".join(argv[1:3]),
                                   self.results.get(argv[1], (0, "")))
        return subprocess.CompletedProcess(argv, rc, out, "ERROR: denied\n")


# What ``text=True`` raises for bytes the locale encoding cannot decode.
UNDECODABLE = UnicodeDecodeError("cp1252", b"abc\x81", 3, 4,
                                 "character maps to <undefined>")


@pytest.fixture
def on_linux(monkeypatch):
    monkeypatch.setattr(cron_mod.platform, "system", lambda: "Linux")


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr(cron_mod.platform, "system", lambda: "Windows")


def _install(runner, **kwargs):
    kwargs.setdefault("runtime_dir", "/opt/memanga")
    kwargs.setdefault("python_path", "/usr/bin/python3")
    return install_schedule(6, 0, runner=runner, **kwargs)


@pytest.mark.usefixtures("on_linux")
class TestCronService:
    def test_install_keeps_unrelated_lines(self):
        runner = FakeScheduler(f"{build_cron_line(15, 3, '/x', '/y')}\n{CRONTAB}")
        result = _install(runner)

        assert result.status is ScheduleStatus.INSTALLED and result.ok
        assert not result.windows
        assert result.entries == (MANAGED,)
        assert runner.written == f"{CRONTAB}{MANAGED}\n"
        assert result.unmanaged == tuple(unmanaged_memanga_lines(CRONTAB))

    def test_install_without_crontab(self):
        runner = FakeScheduler()
        assert _install(runner).status is ScheduleStatus.INSTALLED
        assert runner.written == f"{MANAGED}\n"

    def test_install_passes_paths_to_builder(self):
        runner = FakeScheduler("")
        result = _install(runner, config_dir="/srv/My cfg",
                          source_root="/src/My Checkout")
        assert result.entries == (build_cron_line(
            0, 6, "/opt/memanga", "/usr/bin/python3",
            config_dir="/srv/My cfg", source_root="/src/My Checkout"),)

    def test_install_refuses_unreadable_crontab(self):
        runner = FakeScheduler("", read_rc=1,
                               read_err="crontab: Permission denied\n")
        result = _install(runner)

        assert result.status is ScheduleStatus.UNREADABLE and not result.ok
        assert result.detail == "crontab: Permission denied"
        assert runner.written is None

    def test_install_write_failure(self):
        runner = FakeScheduler(CRONTAB, write_rc=1)
        result = _install(runner)
        assert result.status is ScheduleStatus.FAILED
        assert result.detail == "denied"

    def test_missing_crontab_binary_is_a_result(self):
        runner = FakeScheduler(error=FileNotFoundError("crontab"))
        assert _install(runner).status is ScheduleStatus.UNREADABLE
        assert remove_schedule(runner=runner).status is ScheduleStatus.UNREADABLE
        assert schedule_status(runner=runner).status is ScheduleStatus.UNREADABLE

    def test_timeout_is_a_result(self):
        runner = FakeScheduler(
            error=subprocess.TimeoutExpired(["crontab", "-l"], SCHEDULER_TIMEOUT))
        result = schedule_status(runner=runner)
        assert result.status is ScheduleStatus.UNREADABLE
        assert "timed out" in result.detail

    def test_undecodable_crontab_is_never_rewritten(self):
        """A crontab line in another encoding makes ``crontab -l`` output
        undecodable: report it, never write a crontab rebuilt without it."""
        runner = FakeScheduler(error=UNDECODABLE)
        for result in (_install(runner), remove_schedule(runner=runner),
                       schedule_status(runner=runner)):
            assert result.status is ScheduleStatus.UNREADABLE
            assert result.detail == (
                "output is not valid cp1252 text "
                "(character maps to <undefined> at byte 3)")
        assert runner.written is None and not runner.deleted

    def test_unencodable_crontab_write_fails(self):
        class EncodeFails(FakeScheduler):
            def __call__(self, argv, **kwargs):
                if argv == ["crontab", "-"]:
                    raise UnicodeEncodeError("ascii", "é", 0, 1,
                                             "ordinal not in range(128)")
                return super().__call__(argv, **kwargs)

        result = _install(EncodeFails(CRONTAB))
        assert result.status is ScheduleStatus.FAILED
        assert result.detail == (
            "text cannot be written as ascii (ordinal not in range(128))")

    def test_every_call_is_bounded(self):
        runner = FakeScheduler(f"{MANAGED}\n")
        _install(runner)
        remove_schedule(runner=runner)
        schedule_status(runner=runner)
        for _, kwargs in runner.calls:
            assert kwargs["timeout"] == SCHEDULER_TIMEOUT
            assert kwargs["capture_output"] and kwargs["text"]

    def test_remove_drops_only_managed_line(self):
        runner = FakeScheduler(CRONTAB.replace("\n\n", f"\n{MANAGED}\n\n", 1))
        result = remove_schedule(runner=runner)

        assert result.status is ScheduleStatus.REMOVED
        assert result.entries == (MANAGED,)
        assert runner.written == CRONTAB
        assert not runner.deleted

    def test_remove_last_line_deletes_crontab(self):
        runner = FakeScheduler(f"\n{MANAGED}\n")
        assert remove_schedule(runner=runner).status is ScheduleStatus.REMOVED
        assert runner.deleted and runner.written is None

    def test_remove_without_managed_line_writes_nothing(self):
        runner = FakeScheduler(CRONTAB)
        result = remove_schedule(runner=runner)

        assert result.status is ScheduleStatus.NOT_FOUND and result.ok
        assert result.unmanaged == tuple(unmanaged_memanga_lines(CRONTAB))
        assert runner.written is None and not runner.deleted

    def test_remove_refuses_unreadable_crontab(self):
        runner = FakeScheduler("", read_rc=1, read_err="Permission denied")
        assert remove_schedule(runner=runner).status is ScheduleStatus.UNREADABLE
        assert runner.written is None and not runner.deleted

    def test_remove_write_failure(self):
        runner = FakeScheduler(f"{MANAGED}\n", write_rc=1)
        assert remove_schedule(runner=runner).status is ScheduleStatus.FAILED

    def test_status(self):
        found = schedule_status(runner=FakeScheduler(f"{CRONTAB}{MANAGED}\n"))
        assert found.status is ScheduleStatus.INSTALLED
        assert found.entries == (MANAGED,)

        missing = schedule_status(runner=FakeScheduler(CRONTAB))
        assert missing.status is ScheduleStatus.NOT_FOUND
        assert missing.unmanaged

        none = schedule_status(runner=FakeScheduler())
        assert none.status is ScheduleStatus.NOT_FOUND

    def test_defaults_to_subprocess_run(self, monkeypatch):
        runner = FakeScheduler(f"{MANAGED}\n")
        monkeypatch.setattr(cron_mod.subprocess, "run", runner)
        assert schedule_status().status is ScheduleStatus.INSTALLED
        assert runner.calls


@pytest.mark.usefixtures("on_windows")
class TestTaskSchedulerService:
    def test_install_creates_task(self):
        runner = FakeScheduler()
        result = install_schedule(6, 5, runtime_dir="C:/cfg",
                                  python_path=r"C:\Py\python.exe",
                                  config_dir=r"D:\My cfg", runner=runner)

        assert result.status is ScheduleStatus.INSTALLED and result.windows
        command = build_task_command(r"C:\Py\python.exe", r"D:\My cfg")
        assert result.entries == (command,)
        argvs = [argv for argv, _ in runner.calls]
        assert argvs == [
            ["schtasks", "/create", "/tn", WINDOWS_TASK_NAME, "/tr", command,
             "/sc", "daily", "/st", "06:05", "/f"],
        ]

    def test_install_failure_keeps_existing_task(self):
        """A failed reinstall must not have deleted the task it replaces:
        /create /f overwrites in place, nothing is deleted first."""
        runner = FakeScheduler(results={"/create": (1, ""),
                                        "/query": (0, self.OWN_TASK)})
        result = install_schedule(6, 0, runtime_dir="C:/cfg", runner=runner)
        assert result.status is ScheduleStatus.FAILED
        assert result.detail == "ERROR: denied"
        assert [argv[1] for argv, _ in runner.calls] == ["/create"]

    def test_install_timeout_deletes_nothing(self):
        runner = FakeScheduler(error=subprocess.TimeoutExpired(
            ["schtasks", "/create"], SCHEDULER_TIMEOUT))
        result = install_schedule(6, 0, runtime_dir="C:/cfg", runner=runner)
        assert result.status is ScheduleStatus.FAILED
        assert [argv[1] for argv, _ in runner.calls] == ["/create"]

    def test_remove(self):
        runner = FakeScheduler()
        assert remove_schedule(runner=runner).status is ScheduleStatus.REMOVED
        assert [argv[1] for argv, _ in runner.calls] == ["/delete"]

    OTHER_TASKS = ('"\\Backup","10/26/2026 2:30:00 AM","Ready"\n'
                   '"\\Sub\\MeManga_AutoCheck","N/A","Ready"\n')
    OWN_TASK = f'"\\{WINDOWS_TASK_NAME}","10/26/2026 6:00:00 AM","Ready"\n'

    def test_remove_missing_task(self):
        """The task list was read and does not have the task."""
        runner = FakeScheduler(results={"/delete": (1, ""),
                                        "/query": (0, self.OTHER_TASKS)})
        assert remove_schedule(runner=runner).status is ScheduleStatus.NOT_FOUND
        assert [argv for argv, _ in runner.calls][1] == [
            "schtasks", "/query", "/fo", "csv", "/nh"]

    def test_remove_failure_with_task_present(self):
        runner = FakeScheduler(results={
            "/delete": (1, ""), "/query": (0, self.OTHER_TASKS + self.OWN_TASK)})
        result = remove_schedule(runner=runner)
        assert result.status is ScheduleStatus.FAILED
        assert result.detail == "ERROR: denied"

    def test_remove_with_unreadable_task_list_fails_safe(self):
        """Delete and query both denied, or the scheduler unavailable: a
        failed query is no proof the task is gone."""
        runner = FakeScheduler(results={"/delete": (1, ""), "/query": (1, "")})
        result = remove_schedule(runner=runner)
        assert result.status is ScheduleStatus.FAILED and not result.ok
        assert result.detail == "ERROR: denied"

    def test_remove_with_failing_query_call_fails_safe(self):
        class QueryUnavailable(FakeScheduler):
            def __call__(self, argv, **kwargs):
                if argv[1] == "/query":
                    raise subprocess.TimeoutExpired(argv, SCHEDULER_TIMEOUT)
                return super().__call__(argv, **kwargs)

        runner = QueryUnavailable(results={"/delete": (1, "")})
        assert remove_schedule(runner=runner).status is ScheduleStatus.FAILED

    def test_status_queries_task_by_name(self):
        out = "\nFolder: \\\nTaskName  Next Run Time  Status\n"
        runner = FakeScheduler(results={"/query /tn": (0, out)})
        found = schedule_status(runner=runner)
        assert found.status is ScheduleStatus.INSTALLED
        assert found.entries == ("Folder: \\", "TaskName  Next Run Time  Status")
        assert [argv for argv, _ in runner.calls] == [
            ["schtasks", "/query", "/tn", WINDOWS_TASK_NAME]]

    def test_status_falls_back_to_task_list(self):
        runner = FakeScheduler(results={
            "/query /tn": (1, ""),
            "/query /fo": (0, self.OTHER_TASKS + self.OWN_TASK)})
        found = schedule_status(runner=runner)
        assert found.status is ScheduleStatus.INSTALLED
        assert found.entries == (
            f"\\{WINDOWS_TASK_NAME}  10/26/2026 6:00:00 AM  Ready",)
        assert [argv for argv, _ in runner.calls][1] == [
            "schtasks", "/query", "/fo", "csv", "/nh"]

    def test_status_absent_task(self):
        """The name query failed and the task list, read successfully,
        does not have the root task."""
        missing = schedule_status(runner=FakeScheduler(results={
            "/query /tn": (1, ""), "/query /fo": (0, self.OTHER_TASKS)}))
        assert missing.status is ScheduleStatus.NOT_FOUND and missing.ok

        empty = schedule_status(runner=FakeScheduler(results={
            "/query /tn": (1, ""), "/query /fo": (
                0, "INFO: There are no scheduled tasks presently available.\n")}))
        assert empty.status is ScheduleStatus.NOT_FOUND

    def test_status_inaccessible_task_list_is_unreadable(self):
        """Access denied or an unavailable scheduler is never "no task"."""
        result = schedule_status(
            runner=FakeScheduler(results={"/query": (1, "")}))
        assert result.status is ScheduleStatus.UNREADABLE and not result.ok
        assert result.detail == "ERROR: denied"

    def test_status_query_timeout_is_unreadable(self):
        runner = FakeScheduler(error=subprocess.TimeoutExpired(
            ["schtasks", "/query"], SCHEDULER_TIMEOUT))
        result = schedule_status(runner=runner)
        assert result.status is ScheduleStatus.UNREADABLE
        assert "timed out" in result.detail
        # A hung scheduler is not asked a second time.
        assert len(runner.calls) == 1

    def test_missing_schtasks_is_a_result(self):
        runner = FakeScheduler(error=FileNotFoundError("schtasks"))
        assert install_schedule(6, 0, runtime_dir="C:/cfg",
                                runner=runner).status is ScheduleStatus.FAILED
        assert remove_schedule(runner=runner).status is ScheduleStatus.FAILED
        assert schedule_status(runner=runner).status is ScheduleStatus.UNREADABLE

    def test_undecodable_output_is_a_result(self):
        """``text=True`` decoding can raise UnicodeDecodeError (a
        ValueError, not an OSError); it must not escape the service."""
        runner = FakeScheduler(error=UNDECODABLE)
        assert install_schedule(6, 0, runtime_dir="C:/cfg",
                                runner=runner).status is ScheduleStatus.FAILED
        assert remove_schedule(runner=runner).status is ScheduleStatus.FAILED
        result = schedule_status(runner=runner)
        assert result.status is ScheduleStatus.UNREADABLE
        assert "not valid cp1252 text" in result.detail

        class DeleteThenUndecodable(FakeScheduler):
            def __call__(self, argv, **kwargs):
                if argv[1] == "/query":
                    raise UNDECODABLE
                return super().__call__(argv, **kwargs)

        runner = DeleteThenUndecodable(results={"/delete": (1, "")})
        assert remove_schedule(runner=runner).status is ScheduleStatus.FAILED
