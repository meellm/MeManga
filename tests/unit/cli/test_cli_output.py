"""CLI output and logging behaviour (issue #226): plain output when not on
a terminal, one check summary line, diagnostics on stderr with levels
chosen by -v/-q/MEMANGA_LOG_LEVEL, and the optional rotating log file."""

from __future__ import annotations

import json
import logging
import re
import sys

import pytest

DECORATION = re.compile("[\u2500-\u257f\u2600-\u27bf\U0001f000-\U0001faff]")
TIMESTAMPED = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [A-Z]+ ")


@pytest.fixture
def config_dir(isolated_home):
    return isolated_home / ".config" / "memanga"


@pytest.fixture
def run_cli(monkeypatch, config_dir):
    """Run `cli.main()` with ``argv``; global options go before the
    command, so they're passed separately."""
    def _run(*argv, global_opts=()):
        monkeypatch.setattr(
            sys, "argv",
            ["memanga", "--config-dir", str(config_dir), *global_opts, *argv],
        )
        from memanga import cli
        try:
            cli.main()
        except SystemExit as exc:
            return exc.code
        return 0
    return _run


@pytest.fixture
def seeded(config):
    config.set("manga", [{
        "title": "Alpha", "source": "mangadex.org",
        "url": "https://mangadex.org/title/1/x", "status": "reading",
    }])
    config.save()


@pytest.fixture
def check_stubs(monkeypatch, tmp_path):
    """Stub the network: one new chapter per manga; `log` lists
    (level, message) records a library module emits while checking."""
    from memanga import cli
    from memanga.scrapers.base import Chapter

    log = []

    def _check(manga, *args, **kwargs):
        for level, message in log:
            logging.getLogger("memanga.downloader.updates").log(level, message)
        return [Chapter(number="1")]

    def _download(manga, ch, *args, **kwargs):
        path = tmp_path / f"{manga['title']}-{ch.number}.pdf"
        path.write_bytes(b"pdf")
        return path

    monkeypatch.setattr(cli, "check_for_updates", _check)
    monkeypatch.setattr(cli, "download_chapter", _download)
    monkeypatch.setattr(cli, "_find_chapter_on_backup", lambda *a, **k: None)
    return log


class TestPlainOutput:
    def test_redirected_check_is_plain_with_one_summary_line(
            self, run_cli, seeded, check_stubs, capsys):
        capsys.readouterr()
        assert run_cli("check", "--auto") == 0
        captured = capsys.readouterr()
        out = captured.out
        assert DECORATION.search(out) is None, out
        assert "\x1b[" not in out
        assert "Checking for New Chapters" in out
        summaries = [line for line in out.splitlines() if "Summary" in line]
        assert summaries == [
            "Summary: 1/1 chapters downloaded, 0 failed; checked 1 manga, "
            "0 could not be checked"
        ]
        assert captured.err == ""

    def test_dry_run_summary_line(self, run_cli, seeded, check_stubs, capsys):
        capsys.readouterr()
        assert run_cli("check", "--dry-run") == 0
        out = capsys.readouterr().out
        assert ("Dry run: 1 chapter(s) available for download; checked 1 "
                "manga, 0 could not be checked") in out.splitlines()

    @pytest.mark.parametrize("counts, expected", [
        # dry_run, checked, new, downloaded, failed, errored, unconfirmed
        ((False, 2, 0, 0, 0, 0, 0),
         "Summary: no new chapters found; checked 2 manga, "
         "0 could not be checked"),
        ((False, 2, 3, 2, 1, 1, 0),
         "Summary: 2/3 chapters downloaded, 1 failed; checked 2 manga, "
         "1 could not be checked; next: run 'memanga failed' for details"),
        ((False, 1, 4, 0, 0, 0, 4),
         "Summary: 0/4 chapters downloaded, 0 failed; checked 1 manga, "
         "0 could not be checked, 4 chapter(s) need confirmation; "
         "next: rerun with --download"),
        # Could-not-be-checked alone has no next command: its errors
        # already say why.
        ((False, 2, 1, 1, 0, 1, 0),
         "Summary: 1/1 chapters downloaded, 0 failed; checked 2 manga, "
         "1 could not be checked"),
        ((True, 1, 2, 0, 0, 0, 0),
         "Dry run: 2 chapter(s) available for download; checked 1 manga, "
         "0 could not be checked"),
        # Issue #360: saved but not sent to Kindle; failed downloads
        # still come first.
        ((False, 1, 2, 2, 0, 0, 0, 1),
         "Summary: 2/2 chapters downloaded, 0 failed, 1 not sent to Kindle; "
         "checked 1 manga, 0 could not be checked; "
         "next: run 'memanga send --pending'"),
        ((False, 1, 2, 1, 1, 0, 0, 1),
         "Summary: 1/2 chapters downloaded, 1 failed, 1 not sent to Kindle; "
         "checked 1 manga, 0 could not be checked; "
         "next: run 'memanga failed' for details"),
        # Issue #341: chapters of manual-mode manga are only listed; that
        # is intended, so there is no next command for them.
        ((False, 2, 0, 0, 0, 0, 0, 0, 3),
         "Summary: no chapters to download; checked 2 manga, "
         "0 could not be checked, 3 chapter(s) of manual-mode manga "
         "not downloaded"),
        ((False, 2, 1, 1, 0, 0, 0, 0, 3),
         "Summary: 1/1 chapters downloaded, 0 failed; checked 2 manga, "
         "0 could not be checked, 3 chapter(s) of manual-mode manga "
         "not downloaded"),
        ((False, 2, 1, 0, 0, 0, 1, 0, 3),
         "Summary: 0/1 chapters downloaded, 0 failed; checked 2 manga, "
         "0 could not be checked, 3 chapter(s) of manual-mode manga "
         "not downloaded, 1 chapter(s) need confirmation; "
         "next: rerun with --download"),
        ((True, 2, 1, 0, 0, 0, 0, 0, 3),
         "Dry run: 1 chapter(s) available for download; checked 2 manga, "
         "0 could not be checked, 3 chapter(s) of manual-mode manga "
         "not downloaded"),
    ])
    def test_summary_line_next_action(self, counts, expected):
        """#372: the line ends with what to do next, only when needed."""
        from memanga import cli
        assert cli._check_summary_line(*counts) == expected

    def test_failed_chapter_summary_names_next_step_under_quiet(
            self, run_cli, seeded, check_stubs, capsys, monkeypatch):
        """#372: -q hides the failure warning; the summary still says
        what to run."""
        from memanga import cli
        from memanga.downloader import DownloaderError

        def _download(*args, **kwargs):
            raise DownloaderError("HTTP 404")
        monkeypatch.setattr(cli, "download_chapter", _download)
        capsys.readouterr()
        assert run_cli("check", "--auto", global_opts=["-q"]) == 3
        captured = capsys.readouterr()
        assert "memanga failed" not in captured.err
        summaries = [line for line in captured.out.splitlines()
                     if line.startswith("Summary")]
        assert summaries == [
            "Summary: 0/1 chapters downloaded, 1 failed; checked 1 manga, "
            "0 could not be checked; next: run 'memanga failed' for details"
        ]

    def test_unconfirmed_summary_names_next_step(
            self, run_cli, seeded, check_stubs, capsys, monkeypatch):
        from memanga import cli
        monkeypatch.setattr(cli, "_stdin_is_tty", lambda: False)
        capsys.readouterr()
        assert run_cli("check") == 1
        captured = capsys.readouterr()
        assert captured.out.splitlines()[-1] == (
            "Summary: 0/1 chapters downloaded, 0 failed; checked 1 manga, "
            "0 could not be checked, 1 chapter(s) need confirmation; "
            "next: rerun with --download")
        assert "skipped 1 chapter(s) that need confirmation" in captured.err

    def test_list_table_has_no_borders(self, run_cli, seeded, capsys):
        capsys.readouterr()
        assert run_cli("list", global_opts=["--plain"]) == 0
        out = capsys.readouterr().out
        assert "Alpha" in out
        assert DECORATION.search(out) is None, out

    def test_json_output_is_unchanged(self, run_cli, seeded, capsys):
        capsys.readouterr()
        assert run_cli("list", "--json", global_opts=["--plain"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["manga"][0]["title"] == "Alpha"


class TestLogging:
    WARNING = (logging.WARNING, "Failed to fetch from backup.example: boom")
    INFO = (logging.INFO, "Restarting browser to free memory...")

    def test_library_warning_goes_to_stderr_with_time_and_level(
            self, run_cli, seeded, check_stubs, capsys):
        check_stubs.append(self.WARNING)
        capsys.readouterr()
        assert run_cli("check", "--auto") == 0
        captured = capsys.readouterr()
        assert "Failed to fetch" not in captured.out
        lines = [line for line in captured.err.splitlines()
                 if "Failed to fetch" in line]
        assert len(lines) == 1
        assert TIMESTAMPED.match(lines[0])
        assert lines[0].endswith(
            "WARNING memanga.downloader.updates: "
            "Failed to fetch from backup.example: boom")

    def test_quiet_hides_warnings(self, run_cli, seeded, check_stubs, capsys):
        check_stubs.append(self.WARNING)
        capsys.readouterr()
        assert run_cli("check", "--auto", global_opts=["-q"]) == 0
        captured = capsys.readouterr()
        assert "Failed to fetch" not in captured.err
        assert "Failed to fetch" not in captured.out
        # -q never changes what the command itself reports.
        assert "1/1 chapters downloaded" in captured.out

    def test_check_quiet_keeps_warnings_for_cron(self, run_cli, seeded,
                                                 check_stubs, capsys):
        # The managed cron line runs `check --auto --quiet`: a degraded
        # source must still reach memanga.log, with time and level.
        check_stubs.append(self.WARNING)
        capsys.readouterr()
        assert run_cli("check", "--auto", "--quiet") == 0
        lines = [line for line in capsys.readouterr().err.splitlines()
                 if "Failed to fetch" in line]
        assert len(lines) == 1
        assert TIMESTAMPED.match(lines[0])
        assert " WARNING memanga.downloader.updates: " in lines[0]

    def test_env_level_hides_warnings(self, run_cli, seeded, check_stubs,
                                      capsys, monkeypatch):
        monkeypatch.setenv("MEMANGA_LOG_LEVEL", "error")
        check_stubs.append(self.WARNING)
        capsys.readouterr()
        assert run_cli("check", "--auto") == 0
        assert "Failed to fetch" not in capsys.readouterr().err

    def test_info_needs_verbose(self, run_cli, seeded, check_stubs, capsys,
                                monkeypatch):
        check_stubs.append(self.INFO)
        capsys.readouterr()
        assert run_cli("check", "--auto") == 0
        assert "Restarting browser" not in capsys.readouterr().err

        monkeypatch.setenv("MEMANGA_LOG_LEVEL", "error")
        assert run_cli("check", "--auto", global_opts=["-v"]) == 0
        err = capsys.readouterr().err
        assert "INFO memanga.downloader.updates: Restarting browser" in err

    def test_invalid_env_level_warns_and_keeps_stdout_clean(
            self, run_cli, seeded, capsys, monkeypatch):
        monkeypatch.setenv("MEMANGA_LOG_LEVEL", "loud")
        capsys.readouterr()
        assert run_cli("list", "--json") == 0
        captured = capsys.readouterr()
        json.loads(captured.out)
        assert "Ignoring MEMANGA_LOG_LEVEL='loud'" in captured.err

    def test_verbose_and_quiet_conflict(self, run_cli, capsys):
        assert run_cli("list", global_opts=["-v", "-q"]) == 2

    def test_log_file_in_config_dir(self, run_cli, seeded, check_stubs,
                                    capsys, config_dir):
        check_stubs.extend([self.INFO, self.WARNING])
        capsys.readouterr()
        assert run_cli("check", "--auto", global_opts=["--log-file"]) == 0
        for handler in logging.getLogger().handlers:
            handler.flush()
        all_lines = (config_dir / "diagnostics.log").read_text(
            encoding="utf-8").splitlines()
        assert all(TIMESTAMPED.match(line) for line in all_lines)
        lines = [line for line in all_lines
                 if "memanga.downloader.updates" in line]
        # The file keeps INFO although stderr shows WARNING and up.
        assert len(lines) == 2
        assert "INFO memanga.downloader.updates: Restarting browser" in lines[0]
        assert "WARNING memanga.downloader.updates: Failed to fetch" in lines[1]
        assert "Restarting browser" not in capsys.readouterr().err

    def test_log_file_not_written_by_default(self, run_cli, seeded,
                                             check_stubs, config_dir):
        check_stubs.append(self.WARNING)
        assert run_cli("check", "--auto") == 0
        assert not (config_dir / "diagnostics.log").exists()


class TestCommandDiagnostics:
    """`check`'s own warnings and errors are log records too (issue #226)."""

    @pytest.fixture
    def two_manga(self, config):
        config.set("manga", [
            {"title": "Alpha", "source": "mangadex.org",
             "url": "https://mangadex.org/title/1/x", "status": "reading"},
            {"title": "Beta", "source": "mangadex.org",
             "url": "https://mangadex.org/title/2/x", "status": "reading"},
        ])
        config.save()

    @pytest.fixture
    def alpha_fails(self, monkeypatch, check_stubs):
        from memanga import cli
        from memanga.downloader import DownloaderError
        from memanga.scrapers.base import Chapter

        def _check(manga, *args, **kwargs):
            if manga["title"] == "Alpha":
                raise DownloaderError("HTTP 503")
            return [Chapter(number="1")]
        monkeypatch.setattr(cli, "check_for_updates", _check)

    def test_redirected_warning_and_error_have_time_and_level(
            self, run_cli, two_manga, alpha_fails, capsys):
        capsys.readouterr()
        assert run_cli("check", "--auto") == 3
        err = capsys.readouterr().err.splitlines()
        assert err, "expected diagnostics on stderr"
        assert all(TIMESTAMPED.match(line) for line in err), err
        assert any(line.endswith("ERROR memanga.cli: Alpha: Error: HTTP 503")
                   for line in err), err
        assert any(line.endswith(
            "WARNING memanga.cli: 1/2 manga could not be checked.")
            for line in err), err

    @pytest.mark.parametrize("global_opts, env", [
        (["-q"], None),
        ([], "error"),
    ])
    def test_quiet_hides_command_warnings_keeps_errors(
            self, run_cli, two_manga, alpha_fails, capsys, monkeypatch,
            global_opts, env):
        if env is not None:
            monkeypatch.setenv("MEMANGA_LOG_LEVEL", env)
        capsys.readouterr()
        assert run_cli("check", "--auto", global_opts=global_opts) == 3
        captured = capsys.readouterr()
        assert "ERROR memanga.cli: Alpha: Error: HTTP 503" in captured.err
        assert "could not be checked" not in captured.err
        assert "WARNING" not in captured.err
        # The summary line is a result on stdout and stays.
        assert "1 could not be checked" in captured.out

    def test_command_diagnostics_reach_log_file(
            self, run_cli, two_manga, alpha_fails, capsys, config_dir):
        assert run_cli("check", "--auto", global_opts=["-q", "--log-file"]) == 3
        for handler in logging.getLogger().handlers:
            handler.flush()
        text = (config_dir / "diagnostics.log").read_text(encoding="utf-8")
        assert "ERROR memanga.cli: Alpha: Error: HTTP 503" in text
        # The file keeps warnings even when -q hides them on stderr.
        assert "WARNING memanga.cli: 1/2 manga could not be checked." in text

    @pytest.mark.parametrize("level, shown", [
        (logging.WARNING, True),
        (logging.ERROR, False),
    ])
    def test_partial_chapter_is_a_warning_record(self, capsys, tmp_path,
                                                 level, shown):
        from memanga import cli, output
        from memanga.chapter_pipeline import ChapterOutcome, ChapterStatus

        output.configure_logging(level)
        outcome = ChapterOutcome(
            chapter="5", status=ChapterStatus.PARTIAL,
            path=tmp_path / "Alpha - Chapter 5.pdf",
            missing_pages=[3, 4], total_pages=10,
        )
        cli._ConsoleChapterReporter().saved(outcome)
        err = capsys.readouterr().err
        expected = ("WARNING memanga.cli: Saved partial: Alpha - Chapter 5.pdf"
                    " — 2/10 page(s) missing (pages [3, 4])")
        assert (expected in err) is shown

    def test_interactive_stderr_keeps_rich_rendering(self, capsys):
        from memanga import cli, output

        rendered = []
        output.configure_logging(logging.WARNING, timestamps=False)
        output.set_console_renderer(rendered.append)
        cli._ConsoleChapterReporter().failed(
            type("Outcome", (), {"chapter": "7", "error": "boom"})())
        assert rendered == ["     [red]❌ Failed: boom[/red]"]
        assert capsys.readouterr().err == ""

    def test_without_logging_setup_prints_as_before(self, capsys):
        # cmd_* called directly (the TUI, tests): no handlers installed.
        from memanga import cli

        cli._diagnostic(logging.WARNING, "[yellow]⚠️  careful[/yellow]",
                        "careful")
        assert "careful" in capsys.readouterr().err


class TestPlainKeepsUserData:
    def test_doctor_names_status_in_plain_output(self, run_cli, monkeypatch,
                                                 capsys):
        from memanga import doctor

        results = [
            doctor.CheckResult("config", doctor.OK, "fine"),
            doctor.CheckResult("email", doctor.WARNING, "no address"),
            doctor.CheckResult("state", doctor.FAIL, "cannot read state"),
            doctor.CheckResult("smtp", doctor.SKIP, "not requested"),
        ]
        monkeypatch.setattr(doctor, "run_checks", lambda *a, **k: results)
        capsys.readouterr()
        assert run_cli("doctor") == 1
        rows = [line.split() for line in capsys.readouterr().out.splitlines()]
        assert ["FAIL", "state", "cannot", "read", "state"] in rows
        assert ["WARN", "email", "no", "address"] in rows
        assert ["OK", "config", "fine"] in rows
        assert ["SKIP", "smtp", "not", "requested"] in rows

    def test_title_symbols_survive_plain_list(self, run_cli, config, capsys):
        config.set("manga", [{
            "title": "Love♥Live ★ Stars", "source": "mangadex.org",
            "url": "https://mangadex.org/title/1/x", "status": "reading",
        }])
        config.save()
        capsys.readouterr()
        assert run_cli("list", global_opts=["--plain"]) == 0
        assert "Love♥Live ★ Stars" in capsys.readouterr().out


def test_global_flags_say_they_go_before_the_command():
    from memanga import cli

    parser = cli.build_parser()
    for action in parser._actions:
        if set(action.option_strings) & {"-v", "-q", "--plain", "--log-file"}:
            assert "Goes before the command." in action.help, action.option_strings


class TestSaveAndInterruptDiagnostics:
    """State-save failures and the interrupt flush are log records once
    main() set up logging, and print as before when it did not."""

    @staticmethod
    def _list_raises(monkeypatch, exc):
        from memanga import cli

        def _raise(args):
            raise exc
        monkeypatch.setattr(cli, "cmd_list", _raise)

    @staticmethod
    def _disk_full():
        import errno
        from pathlib import Path
        from memanga.persist import SaveError

        return SaveError(Path("state.json"),
                         OSError(errno.ENOSPC, "No space left on device"))

    def test_interrupt_flush_failure_is_a_timestamped_warning(
            self, run_cli, seeded, monkeypatch, capsys):
        from memanga.state import State

        def _broken_flush(self):
            raise OSError("disk full")
        monkeypatch.setattr(State, "flush", _broken_flush)
        self._list_raises(monkeypatch, KeyboardInterrupt())
        capsys.readouterr()

        assert run_cli("list") == 130
        err = capsys.readouterr().err
        [line] = [ln for ln in err.splitlines() if "Could not save state" in ln]
        assert TIMESTAMPED.match(line)
        assert line.endswith("WARNING memanga.cli: Could not save state: disk full")
        assert "Interrupted" in err

    def test_checkpoint_failure_is_one_timestamped_error(
            self, run_cli, seeded, monkeypatch, capsys):
        from memanga import cli

        self._list_raises(monkeypatch, cli.StateCheckpointError("disk full"))
        capsys.readouterr()

        # -q hides warnings only; the error and the exit code stay.
        assert run_cli("list", global_opts=["-q"]) == 1
        lines = capsys.readouterr().err.splitlines()
        assert len(lines) == 1, lines
        assert TIMESTAMPED.match(lines[0])
        assert lines[0].endswith(
            "ERROR memanga.cli: Could not save state: disk full. Stopped: "
            "nothing more is downloaded or sent while results can't be "
            "recorded.")

    def test_save_error_reaches_log_file(self, run_cli, seeded, monkeypatch,
                                         capsys, config_dir):
        self._list_raises(monkeypatch, self._disk_full())
        capsys.readouterr()

        assert run_cli("list", global_opts=["--log-file"]) == 1
        err = capsys.readouterr().err
        assert "ERROR memanga.cli: Could not save state.json: No space left " \
               "on device. state.json and its backup were not changed" in err
        assert "Traceback" not in err
        for handler in logging.getLogger().handlers:
            handler.flush()
        text = (config_dir / "diagnostics.log").read_text(encoding="utf-8")
        assert "ERROR memanga.cli: Could not save state.json" in text

    @pytest.mark.parametrize("exc, expected", [
        ("checkpoint", ["Could not save state: disk full",
                        "Stopped: nothing more is downloaded"]),
        ("save", ["Could not save state.json: No space left on device",
                  "state.json and its backup were not changed by this save"]),
    ])
    def test_without_logging_setup_prints_and_exits_1(
            self, monkeypatch, capsys, exc, expected):
        from memanga import cli, output

        error = (cli.StateCheckpointError("disk full") if exc == "checkpoint"
                 else self._disk_full())

        def _main():
            raise error
        monkeypatch.setattr(cli, "_main", _main)
        assert not output.logging_configured()

        with pytest.raises(SystemExit) as exit_info:
            cli._run_main()
        assert exit_info.value.code == cli.EXIT_ERROR
        err = " ".join(capsys.readouterr().err.split())
        for text in expected:
            assert text in err

    def test_flush_failure_without_logging_setup_prints(self, monkeypatch,
                                                        capsys):
        from memanga import cli, output

        class _State:
            def flush(self):
                raise OSError("disk full")
        monkeypatch.setattr(cli, "state", _State())
        assert not output.logging_configured()

        cli._flush_state_on_interrupt()
        assert "Could not save state: disk full" in capsys.readouterr().err
