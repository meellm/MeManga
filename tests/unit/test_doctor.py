"""Tests for memanga.doctor health checks (#250).

Network and browser work is stubbed: SMTP login, crontab and Playwright
are replaced with fakes so the suite stays offline and deterministic.
"""

import smtplib
import sys
import types

import pytest

from memanga import doctor


def _run_result(returncode=0, stdout=""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


class TestLocalPathChecks:
    def test_fresh_home_is_ok(self, config, state):
        assert doctor.check_config(config).status == doctor.OK
        assert doctor.check_state(config, state).status == doctor.OK
        assert doctor.check_download_dir(config).status == doctor.OK

    def test_invalid_yaml_fails(self, config):
        config.config_path.write_text("manga: [unclosed\n", encoding="utf-8")
        result = doctor.check_config(config)
        assert result.status == doctor.FAIL
        assert "YAML" in result.message

    def test_non_mapping_yaml_fails(self, config):
        config.config_path.write_text("- just\n- a list\n", encoding="utf-8")
        assert doctor.check_config(config).status == doctor.FAIL

    def test_corrupt_state_fails(self, config, state):
        state.state_path.write_text("{not json", encoding="utf-8")
        result = doctor.check_state(config, state)
        assert result.status == doctor.FAIL
        assert "JSON" in result.message

    def test_download_path_that_is_a_file_fails(self, config, tmp_path):
        target = tmp_path / "not-a-dir"
        target.write_text("x")
        config.set("delivery.download_dir", str(target))
        assert doctor.check_download_dir(config).status == doctor.FAIL

    def test_unwritable_download_dir_fails(self, config, tmp_path, monkeypatch):
        target = tmp_path / "dl"
        target.mkdir()
        config.set("delivery.download_dir", str(target))
        monkeypatch.setattr(doctor, "_probe_writable", lambda d: "Permission denied")
        result = doctor.check_download_dir(config)
        assert result.status == doctor.FAIL
        assert "Permission denied" in result.message


class TestEmailAndKeyring:
    def test_email_skipped_in_local_mode(self, config):
        assert doctor.check_email(config).status == doctor.SKIP

    def test_email_mode_missing_password_fails(self, config, monkeypatch):
        config.set("delivery.mode", "email")
        config.set("email.kindle_email", "me@kindle.com")
        config.set("email.sender_email", "me@gmail.com")
        monkeypatch.setattr(doctor, "get_app_password", lambda cfg: "")
        result = doctor.check_email(config)
        assert result.status == doctor.FAIL
        assert "app password" in result.message
        assert result.details["app_password_set"] is False

    def test_email_mode_complete_is_ok(self, config, monkeypatch):
        config.set("delivery.mode", "email")
        config.set("email.kindle_email", "me@kindle.com")
        config.set("email.sender_email", "me@gmail.com")
        monkeypatch.setattr(doctor, "get_app_password", lambda cfg: "secret-pw")
        result = doctor.check_email(config)
        assert result.status == doctor.OK
        assert "secret-pw" not in repr(result.to_dict())

    def test_plaintext_password_in_config_warns(self, config):
        config.set("email.app_password", "secret-pw")
        result = doctor.check_keyring(config)
        assert result.status == doctor.WARNING
        assert "secret-pw" not in repr(result.to_dict())

    def test_keyring_not_needed_for_local_delivery(self, config):
        assert doctor.check_keyring(config).status == doctor.SKIP

    @pytest.mark.parametrize("backend, expected", [
        (dict(available=True, backend="keyring.backends.SecretService.Keyring", plaintext=False), doctor.OK),
        (dict(available=False, backend="keyring.backends.fail.Keyring", plaintext=False), doctor.WARNING),
        (dict(available=True, backend="keyrings.alt.file.PlaintextKeyring", plaintext=True), doctor.WARNING),
    ])
    def test_keyring_backend_in_email_mode(self, config, monkeypatch, backend, expected):
        config.set("delivery.mode", "email")
        monkeypatch.setattr(doctor, "_keyring_backend", lambda: dict(backend))
        assert doctor.check_keyring(config).status == expected


class TestSmtp:
    def _email_config(self, config, monkeypatch, password="secret-pw"):
        config.set("email.sender_email", "me@gmail.com")
        monkeypatch.setattr(doctor, "get_app_password", lambda cfg: password)

    def test_skipped_unless_live(self, config, monkeypatch):
        def boom(*a):
            raise AssertionError("must not touch the network")
        monkeypatch.setattr(doctor, "_smtp_login", boom)
        assert doctor.check_smtp(config).status == doctor.SKIP

    def test_live_login_ok(self, config, monkeypatch):
        self._email_config(config, monkeypatch)
        calls = []
        monkeypatch.setattr(doctor, "_smtp_login", lambda *a: calls.append(a))
        result = doctor.check_smtp(config, live=True)
        assert result.status == doctor.OK
        assert calls == [("smtp.gmail.com", 587, "me@gmail.com", "secret-pw")]

    def test_auth_failure(self, config, monkeypatch):
        self._email_config(config, monkeypatch)

        def fail(*a):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        monkeypatch.setattr(doctor, "_smtp_login", fail)
        result = doctor.check_smtp(config, live=True)
        assert result.status == doctor.FAIL
        assert "authentication" in result.message

    def test_error_message_masks_password(self, config, monkeypatch):
        self._email_config(config, monkeypatch)

        def fail(*a):
            raise OSError("connection reset while sending secret-pw")
        monkeypatch.setattr(doctor, "_smtp_login", fail)
        result = doctor.check_smtp(config, live=True)
        assert result.status == doctor.FAIL
        assert "secret-pw" not in result.message

    def test_missing_credentials_fail_without_network(self, config, monkeypatch):
        monkeypatch.setattr(doctor, "get_app_password", lambda cfg: "")
        monkeypatch.setattr(doctor, "_smtp_login", lambda *a: pytest.fail("network"))
        assert doctor.check_smtp(config, live=True).status == doctor.FAIL


class TestScheduler:
    def _line(self, python=sys.executable):
        return f"0 6 * * * cd /opt/memanga && {python} -m memanga check --auto --quiet >> /opt/memanga/memanga.log 2>&1"

    def _check(self, config, stdout="", returncode=0, system="Linux"):
        runner = lambda *a, **k: _run_result(returncode, stdout)
        return doctor.check_scheduler(config, runner=runner, system=system)

    def test_enabled_and_installed_ok(self, config):
        config.set("cron.enabled", True)
        result = self._check(config, self._line() + "\n")
        assert result.status == doctor.OK
        assert result.details["installed"] is True

    def test_nothing_configured_ok(self, config):
        assert self._check(config, "", returncode=1).status == doctor.OK

    def test_enabled_but_not_installed_warns(self, config):
        config.set("cron.enabled", True)
        result = self._check(config, "", returncode=1)
        assert result.status == doctor.WARNING
        assert "cron install" in result.message

    def test_installed_but_disabled_warns(self, config):
        assert self._check(config, self._line()).status == doctor.WARNING

    def test_invalid_time_fails(self, config):
        config.set("cron.enabled", True)
        config.set("cron.time", "25:99")
        assert self._check(config, self._line()).status == doctor.FAIL

    def test_missing_interpreter_warns(self, config):
        config.set("cron.enabled", True)
        result = self._check(config, self._line("/nonexistent/venv/bin/python3"))
        assert result.status == doctor.WARNING

    def test_duplicate_entries_warn(self, config):
        config.set("cron.enabled", True)
        line = self._line()
        assert self._check(config, f"{line}\n{line}\n").status == doctor.WARNING

    def test_wrapped_entry_is_accepted(self, config):
        """Hand-written wrappers such as flock + bash -lc stay valid."""
        config.set("cron.enabled", True)
        line = (f"0 5 * * * /usr/bin/flock -n /tmp/x.lock /bin/bash -lc "
                f"'cd /opt/memanga && {sys.executable} -m memanga check --auto --quiet'")
        assert self._check(config, line).status == doctor.OK

    def test_crontab_unavailable(self, config):
        def missing(*a, **k):
            raise FileNotFoundError("crontab")
        assert doctor.check_scheduler(config, runner=missing, system="Linux").status == doctor.SKIP
        config.set("cron.enabled", True)
        assert doctor.check_scheduler(config, runner=missing, system="Linux").status == doctor.WARNING

    def test_windows_task_query(self, config):
        config.set("cron.enabled", True)
        calls = []

        def runner(argv, **k):
            calls.append(argv)
            return _run_result(0)
        result = doctor.check_scheduler(config, runner=runner, system="Windows")
        assert result.status == doctor.OK
        assert calls[0][:2] == ["schtasks", "/query"]


class TestSources:
    def test_no_cache_skips(self, config, state):
        assert doctor.check_sources(config, state).status == doctor.SKIP

    def test_tracked_source_in_error_warns(self, config, state):
        config.set("manga", [dict(title="A", source="good.test", url="https://good.test/a"),
                             dict(title="B", sources=[dict(source="bad.test", url="https://bad.test/b")])])
        state.update_source_health("good.test", True)
        for _ in range(3):
            state.update_source_health("bad.test", False, "boom")
        state.update_source_health("other.test", False, "x")
        result = doctor.check_sources(config, state)
        assert result.status == doctor.WARNING
        assert result.details["tracked_errors"] == ["bad.test"]
        assert result.details["cached"] == 3

    def test_untracked_errors_do_not_warn(self, config, state):
        for _ in range(3):
            state.update_source_health("other.test", False, "x")
        result = doctor.check_sources(config, state)
        assert result.status == doctor.OK
        assert result.details["error"] == 1


class TestBrowsers:
    def _installed(self, launched=None, error=None):
        return dict(installed=True, executable="/x", launched=launched, error=error)

    def test_matches_gui_required_browsers(self):
        from memanga.gui import _REQUIRED_BROWSERS
        assert doctor.REQUIRED_BROWSERS == _REQUIRED_BROWSERS

    def test_playwright_missing_fails(self, monkeypatch):
        def no_playwright(launch):
            raise ImportError("playwright")
        monkeypatch.setattr(doctor, "_probe_browsers", no_playwright)
        result = doctor.check_browsers()
        assert result.status == doctor.FAIL
        assert "not installed" in result.message

    def test_missing_browser_fails(self, monkeypatch):
        probe = dict(firefox=self._installed(),
                     chromium=dict(installed=False, executable="/y", launched=None, error=None))
        monkeypatch.setattr(doctor, "_probe_browsers", lambda launch: probe)
        result = doctor.check_browsers()
        assert result.status == doctor.FAIL
        assert "chromium" in result.message
        assert "playwright install" in result.message

    def test_installed_ok_without_launch(self, monkeypatch):
        seen = []

        def probe(launch):
            seen.append(launch)
            return dict(firefox=self._installed(), chromium=self._installed())
        monkeypatch.setattr(doctor, "_probe_browsers", probe)
        result = doctor.check_browsers()
        assert result.status == doctor.OK
        assert seen == [False]

    def test_launch_failure_fails(self, monkeypatch):
        probe = dict(firefox=self._installed(launched=True),
                     chromium=self._installed(launched=False, error="crashed"))
        monkeypatch.setattr(doctor, "_probe_browsers", lambda launch: probe)
        result = doctor.check_browsers(launch=True)
        assert result.status == doctor.FAIL
        assert result.details["browsers"]["chromium"]["error"] == "crashed"


class TestRunnerAndReport:
    def test_selection_keeps_canonical_order(self, config, state):
        results = doctor.run_checks(config, state, only={"state", "config"})
        assert [r.name for r in results] == ["config", "state"]

    def test_crashing_check_becomes_fail(self, config, state, monkeypatch):
        def boom(c, s):
            raise RuntimeError("kaboom")
        monkeypatch.setattr(doctor, "check_config", boom)
        results = doctor.run_checks(config, state, only={"config"})
        assert results[0].status == doctor.FAIL
        assert "kaboom" in results[0].message

    def test_report_shape_and_exit_codes(self):
        results = [
            doctor.CheckResult("config", doctor.OK, "fine"),
            doctor.CheckResult("smtp", doctor.SKIP, "not run"),
            doctor.CheckResult("scheduler", doctor.WARNING, "hmm"),
        ]
        report = doctor.build_report(results)
        assert report["schema_version"] == doctor.SCHEMA_VERSION
        assert report["status"] == doctor.WARNING
        assert report["summary"] == dict(ok=1, warning=1, fail=0, skip=1)
        assert report["checks"][0] == dict(name="config", status="ok", message="fine", details={})
        assert doctor.exit_code(results) == 0
        assert doctor.exit_code(results, strict=True) == 1
        results.append(doctor.CheckResult("browsers", doctor.FAIL, "missing"))
        assert doctor.exit_code(results) == 1

    def test_all_skipped_is_ok(self):
        results = [doctor.CheckResult("smtp", doctor.SKIP, "not run")]
        assert doctor.overall_status(results) == doctor.OK
