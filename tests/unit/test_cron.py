"""Tests for memanga.cron shell-safe crontab line construction (#109)."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

import memanga

from memanga.cron import (
    MANAGED_MARKER,
    build_cron_line,
    build_task_command,
    is_managed_line,
    managed_lines,
    quote_cron_path,
    read_crontab,
    remove_managed_lines,
    replace_managed_line,
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
