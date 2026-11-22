"""Tests for `memanga setup` steps (issue #217).

Playwright and the browser installer are replaced with fakes, so nothing
is downloaded, launched or run with privileges.
"""

import shlex
import subprocess
import sys
import types

import pytest

from memanga import doctor, first_run


def _browser(installed=True, launched=None, error=None, missing_dependencies=False):
    return dict(installed=installed, executable="/x", launched=launched,
                error=error, missing_dependencies=missing_dependencies)


class FakeProbe:
    """Stands in for doctor._probe_browsers; installs on the first run call."""

    def __init__(self, installed=("firefox", "chromium"), launch_ok=True,
                 missing_dependencies=False, unbuilt=()):
        self.installed = set(installed)
        # Found by executable_path, but the headless build is absent.
        self.unbuilt = set(unbuilt)
        self.launch_ok = launch_ok
        self.missing_dependencies = missing_dependencies
        self.calls = []

    def __call__(self, launch):
        self.calls.append(launch)
        result = {}
        for name in doctor.REQUIRED_BROWSERS:
            if name not in self.installed:
                result[name] = _browser(installed=False)
            elif launch and name in self.unbuilt:
                result[name] = _browser(
                    launched=False,
                    error=f"BrowserType.launch: Executable doesn't exist at /cache/{name}-shell")
            elif launch:
                result[name] = _browser(
                    launched=self.launch_ok,
                    error=None if self.launch_ok else "BrowserType.launch:",
                    missing_dependencies=not self.launch_ok and self.missing_dependencies)
            else:
                result[name] = _browser()
        return result


class FakeRunner:
    def __init__(self, probe=None, returncode=0, exc=None):
        self.probe = probe
        self.returncode = returncode
        self.exc = exc
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.exc:
            raise self.exc
        if self.probe is not None and self.returncode == 0:
            # Installs only the builds the command named.
            names = set(argv[argv.index("install") + 1:])
            self.probe.installed.update(names)
            self.probe.unbuilt.difference_update(names)
        return types.SimpleNamespace(returncode=self.returncode)


@pytest.fixture(autouse=True)
def _not_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)


class TestBrowserLaunchError:
    MISSING = ("BrowserType.launch: Executable doesn't exist at /cache/firefox-1/firefox\n"
               "╔════════╗\n║ Looks like Playwright was just installed or updated. ║\n"
               "║     playwright install     ║\n╚════════╝")
    DEPS = ("BrowserType.launch: \n╔════╗\n"
            "║ Host system is missing dependencies to run browsers. ║\n"
            "║     sudo playwright install-deps     ║\n╚════╝")

    def test_missing_executable_points_to_setup(self):
        error = first_run.browser_launch_error(RuntimeError(self.MISSING))
        assert isinstance(error, first_run.BrowserSetupError)
        assert isinstance(error, RuntimeError)
        text = str(error)
        assert "Executable doesn't exist at /cache/firefox-1/firefox" in text
        assert "memanga setup" in text
        assert "╔" not in text and "Looks like" not in text

    def test_missing_libraries_points_to_setup(self):
        error = first_run.browser_launch_error(RuntimeError(self.DEPS))
        assert "system libraries" in str(error)
        assert "memanga setup" in str(error)
        assert first_run.missing_host_dependencies(RuntimeError(self.DEPS))

    def test_other_errors_are_left_alone(self):
        assert first_run.browser_launch_error(RuntimeError("Timeout 30000ms")) is None
        assert not first_run.missing_host_dependencies(RuntimeError("crashed"))


class TestCommands:
    def test_install_uses_this_interpreter(self):
        assert first_run.install_command(["firefox"]) == [
            sys.executable, "-m", "playwright", "install", "firefox"]

    def test_frozen_install_uses_bundled_driver(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        from playwright._impl import _driver
        monkeypatch.setattr(_driver, "compute_driver_executable",
                            lambda: ("/app/node", "/app/cli.js"))
        assert first_run.install_command(["chromium"]) == [
            "/app/node", "/app/cli.js", "install", "chromium"]

    def test_deps_command_only_on_linux(self):
        text = first_run.deps_command_text(["firefox", "chromium"], system="Linux")
        assert text.startswith("sudo ")
        assert text.endswith("-m playwright install-deps firefox chromium")
        assert first_run.deps_command_text(["firefox"], system="Darwin") is None
        assert first_run.deps_command_text(["firefox"], system="Windows") is None

    def test_frozen_hints_use_bundled_driver(self, monkeypatch):
        # A frozen build has no `python -m playwright`.
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        from playwright._impl import _driver
        monkeypatch.setattr(_driver, "compute_driver_executable",
                            lambda: ("/app/node", "/app/cli.js"))
        assert first_run.deps_command_text(["firefox"], system="Linux") == (
            "sudo /app/node /app/cli.js install-deps firefox")
        assert first_run.manual_install_text(["firefox"], system="Linux") == (
            "/app/node /app/cli.js install firefox")

    def test_manual_install_uses_this_interpreter(self):
        assert first_run.manual_install_text(["chromium"], system="Linux") == shlex.join(
            [sys.executable, "-m", "playwright", "install", "chromium"])

    def test_manual_install_quotes_spaced_path_for_posix(self, monkeypatch):
        monkeypatch.setattr(sys, "executable", "/opt/my python/bin/python")
        assert first_run.manual_install_text(["firefox"], system="Linux") == (
            "'/opt/my python/bin/python' -m playwright install firefox")
        assert first_run.manual_install_text(["firefox"], system="Darwin") == (
            "'/opt/my python/bin/python' -m playwright install firefox")

    def test_manual_install_quotes_spaced_path_for_windows(self, monkeypatch):
        # Command Prompt groups with double quotes; PowerShell reads a
        # quoted first word as a string unless `&` calls it.
        monkeypatch.setattr(sys, "executable", r"C:\Program Files\Python312\python.exe")
        text = first_run.manual_install_text(["firefox", "chromium"], system="Windows")
        assert text.splitlines() == [
            "",
            r'  Command Prompt: "C:\Program Files\Python312\python.exe" -m playwright '
            "install firefox chromium",
            r"  PowerShell:     & 'C:\Program Files\Python312\python.exe' -m playwright "
            "install firefox chromium",
        ]

    def test_powershell_quoting_expands_nothing(self, monkeypatch):
        # Single quotes keep `$` and backticks literal; a quote is doubled.
        monkeypatch.setattr(sys, "executable", r"C:\Users\O'Neil $x\py`env\python.exe")
        text = first_run.manual_install_text(["firefox"], system="Windows")
        powershell = text.splitlines()[2].split(":", 1)[1].strip()
        assert powershell == (
            r"& 'C:\Users\O''Neil $x\py`env\python.exe' -m playwright install firefox")

    def test_unquoted_windows_path_gives_one_command(self, monkeypatch):
        monkeypatch.setattr(sys, "executable", r"C:\Python312\python.exe")
        assert first_run.manual_install_text(["firefox"], system="Windows") == (
            r"C:\Python312\python.exe -m playwright install firefox")


class TestConfigStep:
    def test_creates_default_config_once(self, config):
        path = config.config_path
        assert not path.exists()
        result = first_run.setup_config(config)
        assert result.status == doctor.OK
        assert result.details["created"] is True
        assert path.exists()
        assert "default settings" in result.message

        path.write_text("manga: []\nedited: yes\n", encoding="utf-8")
        again = first_run.setup_config(config)
        assert again.status == doctor.OK
        assert again.details["created"] is False
        assert "edited: yes" in path.read_text(encoding="utf-8")

    def test_broken_config_is_reported_not_overwritten(self, isolated_home):
        from memanga.config import Config
        root = isolated_home / ".config" / "memanga"
        root.mkdir(parents=True, exist_ok=True)
        (root / "config.yaml").write_text("manga: [unclosed\n", encoding="utf-8")
        cfg = Config(root, tolerate_errors=True)
        result = first_run.setup_config(cfg)
        assert result.status == doctor.FAIL
        assert (root / "config.yaml").read_text(encoding="utf-8") == "manga: [unclosed\n"


class TestDownloadDirStep:
    def test_creates_missing_directory(self, config, tmp_path):
        target = tmp_path / "new" / "downloads"
        config.set("delivery.download_dir", str(target))
        result = first_run.setup_download_dir(config)
        assert result.status == doctor.OK
        assert result.details["created"] is True
        assert target.is_dir()
        again = first_run.setup_download_dir(config)
        assert again.status == doctor.OK
        assert again.details["created"] is False

    def test_file_in_the_way_fails(self, config, tmp_path):
        target = tmp_path / "taken"
        target.write_text("not a folder")
        config.set("delivery.download_dir", str(target))
        result = first_run.setup_download_dir(config)
        assert result.status == doctor.FAIL
        assert target.is_file()


class TestBrowsersStep:
    def test_installed_browsers_are_launched_not_downloaded(self):
        probe, runner = FakeProbe(), FakeRunner()
        result = first_run.setup_browsers(probe=probe, runner=runner)
        assert result.status == doctor.OK
        assert probe.calls == [False, True]
        assert runner.calls == []

    def test_missing_without_terminal_never_downloads(self):
        probe = FakeProbe(installed=("firefox",))
        runner = FakeRunner(probe)
        asked = []
        result = first_run.setup_browsers(probe=probe, runner=runner, can_prompt=False,
                                          confirm=lambda q: asked.append(q) or True)
        assert result.status == doctor.FAIL
        assert "chromium" in result.message
        assert "--install-browsers" in result.message
        assert "playwright install chromium" in result.message
        assert runner.calls == [] and asked == []

    def test_missing_hint_on_windows_is_pasteable(self, monkeypatch):
        monkeypatch.setattr(sys, "executable", r"C:\Program Files\Python312\python.exe")
        probe = FakeProbe(installed=("firefox",))
        result = first_run.setup_browsers(probe=probe, runner=FakeRunner(probe),
                                          system="Windows")
        assert result.status == doctor.FAIL
        lines = result.message.splitlines()
        assert lines[0].endswith("or install by hand: ")
        assert lines[1] == (r'  Command Prompt: "C:\Program Files\Python312\python.exe" '
                            "-m playwright install chromium")
        assert lines[2] == (r"  PowerShell:     & 'C:\Program Files\Python312\python.exe' "
                            "-m playwright install chromium")

    def test_posix_hint_is_not_wrapped_in_quotes(self, monkeypatch):
        monkeypatch.setattr(sys, "executable", "/opt/my python/bin/python")
        probe = FakeProbe(installed=("firefox",))
        result = first_run.setup_browsers(probe=probe, runner=FakeRunner(probe),
                                          system="Linux")
        assert result.message.endswith(
            "or install by hand: '/opt/my python/bin/python' -m playwright install chromium")

    def test_no_install_flag_never_asks(self):
        probe = FakeProbe(installed=())
        runner = FakeRunner(probe)
        asked = []
        result = first_run.setup_browsers(install=False, probe=probe, runner=runner,
                                          can_prompt=True,
                                          confirm=lambda q: asked.append(q) or True)
        assert result.status == doctor.FAIL
        assert runner.calls == [] and asked == []

    def test_install_flag_downloads_only_missing(self):
        probe = FakeProbe(installed=("firefox",))
        runner = FakeRunner(probe)
        notes = []
        result = first_run.setup_browsers(install=True, probe=probe, runner=runner,
                                          notify=notes.append)
        assert result.status == doctor.OK
        argv, kwargs = runner.calls[0]
        assert argv == [sys.executable, "-m", "playwright", "install", "chromium"]
        assert kwargs["timeout"] == first_run.INSTALL_TIMEOUT
        assert "env" not in kwargs
        assert result.details["installed_now"] == ["chromium"]
        assert notes and "chromium" in notes[0]
        assert probe.calls == [False, False, True]

    def test_terminal_answer_decides(self):
        probe = FakeProbe(installed=())
        runner = FakeRunner(probe)
        questions = []
        declined = first_run.setup_browsers(probe=probe, runner=runner, can_prompt=True,
                                            confirm=lambda q: questions.append(q) or False)
        assert declined.status == doctor.FAIL
        assert runner.calls == []
        assert "firefox, chromium" in questions[0]

        accepted = first_run.setup_browsers(probe=probe, runner=runner, can_prompt=True,
                                            confirm=lambda q: True)
        assert accepted.status == doctor.OK
        assert len(runner.calls) == 1

    def test_missing_headless_build_is_installed_then_launched(self):
        probe = FakeProbe(unbuilt=("chromium",))
        runner = FakeRunner(probe)
        result = first_run.setup_browsers(install=True, probe=probe, runner=runner)
        assert result.status == doctor.OK
        assert [argv for argv, _ in runner.calls] == [
            [sys.executable, "-m", "playwright", "install", "chromium"]]
        assert result.details["installed_now"] == ["chromium"]
        assert probe.calls == [False, True, False, True]

    def test_missing_headless_build_without_consent(self):
        probe = FakeProbe(unbuilt=("chromium",))
        runner = FakeRunner(probe)
        result = first_run.setup_browsers(probe=probe, runner=runner)
        assert result.status == doctor.FAIL
        assert "--install-browsers" in result.message
        assert runner.calls == []

    def test_yes_covers_only_the_builds_it_named(self):
        # Firefox is missing; Chromium's headless build turns up only when
        # it is launched. A yes for Firefox must not download Chromium.
        probe = FakeProbe(installed=("chromium",), unbuilt=("chromium",))
        runner = FakeRunner(probe)
        answers = iter([True, False])
        questions = []

        def confirm(question):
            questions.append(question)
            return next(answers)
        result = first_run.setup_browsers(probe=probe, runner=runner,
                                          can_prompt=True, confirm=confirm)
        assert result.status == doctor.FAIL
        assert [argv for argv, _ in runner.calls] == [
            [sys.executable, "-m", "playwright", "install", "firefox"]]
        assert len(questions) == 2
        assert "firefox" in questions[0] and "chromium" not in questions[0]
        assert "chromium" in questions[1]
        assert "chromium" in result.message

    def test_second_yes_downloads_the_second_build(self):
        probe = FakeProbe(installed=("chromium",), unbuilt=("chromium",))
        runner = FakeRunner(probe)
        questions = []
        result = first_run.setup_browsers(
            probe=probe, runner=runner, can_prompt=True,
            confirm=lambda q: questions.append(q) or True)
        assert result.status == doctor.OK
        assert [argv[-1] for argv, _ in runner.calls] == ["firefox", "chromium"]
        assert len(questions) == 2
        assert result.details["installed_now"] == ["firefox", "chromium"]

    def test_install_flag_covers_later_builds_without_asking(self):
        probe = FakeProbe(installed=("chromium",), unbuilt=("chromium",))
        runner = FakeRunner(probe)
        asked = []
        result = first_run.setup_browsers(
            install=True, probe=probe, runner=runner, can_prompt=True,
            confirm=lambda q: asked.append(q) or False)
        assert result.status == doctor.OK
        assert len(runner.calls) == 2
        assert asked == []

    def test_installer_failure_fails(self):
        probe = FakeProbe(installed=())
        result = first_run.setup_browsers(install=True, probe=probe,
                                          runner=FakeRunner(probe, returncode=1))
        assert result.status == doctor.FAIL
        assert "code 1" in result.message

    def test_installer_timeout_fails(self):
        probe = FakeProbe(installed=())
        runner = FakeRunner(exc=subprocess.TimeoutExpired("playwright", 1))
        result = first_run.setup_browsers(install=True, probe=probe, runner=runner)
        assert result.status == doctor.FAIL
        assert "did not finish" in result.message

    def test_still_missing_after_install_fails(self):
        probe = FakeProbe(installed=())
        runner = FakeRunner()  # reports success but installs nothing
        result = first_run.setup_browsers(install=True, probe=probe, runner=runner)
        assert result.status == doctor.FAIL
        assert "still missing" in result.message

    def test_missing_libraries_reported_never_installed(self):
        probe = FakeProbe(launch_ok=False, missing_dependencies=True)
        runner = FakeRunner(probe)
        result = first_run.setup_browsers(install=True, probe=probe, runner=runner,
                                          system="Linux")
        assert result.status == doctor.FAIL
        assert "install-deps" in result.message
        assert "does not install system packages" in result.message
        assert runner.calls == []

    def test_missing_libraries_elsewhere_has_no_sudo(self):
        probe = FakeProbe(launch_ok=False, missing_dependencies=True)
        result = first_run.setup_browsers(probe=probe, system="Darwin")
        assert result.status == doctor.FAIL
        assert "sudo" not in result.message

    def test_other_launch_failure_shows_error(self):
        probe = FakeProbe(launch_ok=False)
        result = first_run.setup_browsers(probe=probe)
        assert result.status == doctor.FAIL
        assert "could not start" in result.message

    def test_playwright_missing(self):
        def probe(launch):
            raise ImportError("playwright")
        result = first_run.setup_browsers(probe=probe)
        assert result.status == doctor.FAIL
        assert "reinstall MeManga" in result.message


class TestRunSetup:
    def test_reports_each_step_in_order(self, config):
        seen = []
        results = first_run.run_setup(config, report=seen.append, probe=FakeProbe())
        assert [r.name for r in results] == ["config", "download_dir", "browsers"]
        assert seen == results
        assert doctor.overall_status(results) == doctor.OK
        assert config.download_dir.is_dir()
