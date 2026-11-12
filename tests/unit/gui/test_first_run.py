"""First-run questions: the browser download can be skipped (issue #344)
and a new library is asked where downloads go (issue #370)."""

from __future__ import annotations

import pytest


@pytest.fixture
def gui(monkeypatch):
    import memanga.gui as gui_mod
    return gui_mod


class _FakeInstall:
    """Stands in for FirefoxInstallDialog; plays back queued outcomes."""

    outcomes: list = []
    runs = 0

    def __init__(self, parent=None):
        self._cancelled = False

    def run_install(self):
        type(self).runs += 1
        ok, error, cancelled = type(self).outcomes.pop(0)
        self._cancelled = cancelled
        return ok, error


@pytest.fixture
def prompts(gui, monkeypatch):
    """Missing browsers, scripted answers, a fake installer.

    ``answers`` are returned by the prompt in order; ``asked`` records
    the failure text each prompt was shown with."""
    import memanga.gui.components.firefox_install_dialog as dialog_mod
    script = {"answers": [], "asked": []}

    def _ask(failure=None):
        script["asked"].append(failure)
        return script["answers"].pop(0)

    _FakeInstall.outcomes = []
    _FakeInstall.runs = 0
    monkeypatch.setattr(gui, "_check_playwright_browsers", lambda: False)
    monkeypatch.setattr(gui, "_ask_browser_install", _ask)
    monkeypatch.setattr(dialog_mod, "FirefoxInstallDialog", _FakeInstall)
    return script


class TestBrowserInstallCanBeSkipped:
    def test_installed_browsers_ask_nothing(self, gui, config, monkeypatch):
        monkeypatch.setattr(gui, "_check_playwright_browsers", lambda: True)
        monkeypatch.setattr(gui, "_ask_browser_install",
                            lambda failure=None: pytest.fail("asked"))
        assert gui._ensure_browsers(config) is True
        assert not config.get(gui.BROWSER_SKIP_KEY)

    def test_skip_opens_the_app_and_is_remembered(self, gui, config, prompts):
        prompts["answers"] = ["skip"]
        assert gui._ensure_browsers(config) is False
        assert config.get(gui.BROWSER_SKIP_KEY) is True
        assert _FakeInstall.runs == 0
        # Saved, so the next launch knows too.
        from memanga.config import Config
        assert Config(config.config_dir).get(gui.BROWSER_SKIP_KEY) is True

    def test_after_a_skip_the_next_launch_does_not_ask(self, gui, config,
                                                       prompts):
        config.set(gui.BROWSER_SKIP_KEY, True)
        assert gui._ensure_browsers(config) is False
        assert prompts["asked"] == []

    def test_quit_exits(self, gui, config, prompts):
        prompts["answers"] = ["quit"]
        with pytest.raises(SystemExit) as exc:
            gui._ensure_browsers(config)
        assert exc.value.code == 0
        assert not config.get(gui.BROWSER_SKIP_KEY)

    def test_install_success(self, gui, config, prompts):
        prompts["answers"] = ["install"]
        _FakeInstall.outcomes = [(True, "", False)]
        assert gui._ensure_browsers(config) is True
        assert prompts["asked"] == [None]

    def test_failed_install_asks_again_with_the_reason_and_can_skip(
            self, gui, config, prompts):
        prompts["answers"] = ["install", "skip"]
        _FakeInstall.outcomes = [(False, "no route to host", False)]
        assert gui._ensure_browsers(config) is False
        assert prompts["asked"] == [None, "no route to host"]
        assert config.get(gui.BROWSER_SKIP_KEY) is True

    def test_failed_install_can_be_retried(self, gui, config, prompts):
        prompts["answers"] = ["install", "install"]
        _FakeInstall.outcomes = [(False, "timeout", False), (True, "", False)]
        assert gui._ensure_browsers(config) is True
        assert _FakeInstall.runs == 2

    def test_cancelled_install_is_not_reported_as_a_failure(
            self, gui, config, prompts):
        prompts["answers"] = ["install", "skip"]
        _FakeInstall.outcomes = [(False, "", True)]
        gui._ensure_browsers(config)
        assert prompts["asked"] == [None, None]

    def test_browsers_found_later_clear_the_skip(self, gui, config,
                                                 monkeypatch):
        config.set(gui.BROWSER_SKIP_KEY, True)
        monkeypatch.setattr(gui, "_check_playwright_browsers", lambda: True)
        assert gui._ensure_browsers(config) is True
        assert config.get(gui.BROWSER_SKIP_KEY) is False

    def test_works_without_a_config(self, gui, prompts):
        prompts["answers"] = ["skip"]
        assert gui._ensure_browsers() is False


class _Online:
    """A network monitor that is always online."""
    is_online = True

    def stop(self):
        pass

    def set_enabled(self, enabled):
        pass


def _go_online(app_window, monkeypatch):
    # The real monitor probes the network from a thread; its answer
    # must not decide these tests.
    app_window.network.stop()
    monkeypatch.setattr(app_window, "network", _Online())


class TestSettingsBrowserSection:
    def _page(self, app_window):
        return app_window._pages["settings"]

    def test_status_follows_what_launch_found(self, app_window):
        from memanga.gui.pages.settings_tabs import advanced
        page = self._page(app_window)
        for found, text in ((None, advanced.BROWSERS_UNKNOWN_TEXT),
                            (False, advanced.BROWSERS_MISSING_TEXT),
                            (True, advanced.BROWSERS_INSTALLED_TEXT)):
            app_window.browsers_installed = found
            page._refresh_browser_status()
            assert page._browser_hint.text() == text
            assert page._browser_install_btn.accessibleDescription() == text

    def test_install_from_settings_clears_the_skip(self, app_window,
                                                   monkeypatch, gui):
        import memanga.gui.components.firefox_install_dialog as dialog_mod
        from memanga.gui.pages import settings as settings_mod
        from memanga.gui.pages.settings_tabs import advanced
        _FakeInstall.outcomes = [(True, "", False)]
        _FakeInstall.runs = 0
        monkeypatch.setattr(dialog_mod, "FirefoxInstallDialog", _FakeInstall)
        toasts = []
        monkeypatch.setattr(settings_mod, "Toast",
                            lambda parent, msg, **k: toasts.append(msg))
        _go_online(app_window, monkeypatch)
        app_window.config.set(gui.BROWSER_SKIP_KEY, True)
        app_window.browsers_installed = False
        page = self._page(app_window)

        page._install_browsers()

        assert _FakeInstall.runs == 1
        assert app_window.browsers_installed is True
        assert app_window.config.get(gui.BROWSER_SKIP_KEY) is False
        assert page._browser_hint.text() == advanced.BROWSERS_INSTALLED_TEXT
        assert toasts == ["Browser components installed"]

    def test_failed_install_from_settings_keeps_the_status(
            self, app_window, monkeypatch):
        import memanga.gui.components.firefox_install_dialog as dialog_mod
        from memanga.gui.pages import settings as settings_mod
        _FakeInstall.outcomes = [(False, "boom", False)]
        monkeypatch.setattr(dialog_mod, "FirefoxInstallDialog", _FakeInstall)
        monkeypatch.setattr(settings_mod, "Toast", lambda *a, **k: None)
        _go_online(app_window, monkeypatch)
        app_window.browsers_installed = False
        self._page(app_window)._install_browsers()
        assert app_window.browsers_installed is False


class TestDownloadLocation:
    def test_asked_for_a_new_library_once(self, config):
        from memanga.gui.components.download_location_dialog import (
            CONFIRMED_KEY, needs_download_location)
        assert needs_download_location(config)
        config.set(CONFIRMED_KEY, True)
        assert not needs_download_location(config)

    def test_library_with_manga_is_left_alone(self, config, sample_manga):
        from memanga.gui.components.download_location_dialog import (
            needs_download_location)
        config.set("manga", [sample_manga])
        assert not needs_download_location(config)

    def test_folder_check(self, config, tmp_path):
        from memanga.gui.components.download_location_dialog import (
            download_dir_problem)
        before = config.get("delivery.download_dir")
        assert download_dir_problem(config, "   ")
        assert download_dir_problem(config, str(tmp_path / "new" / "folder")) is None
        a_file = tmp_path / "file.txt"
        a_file.write_text("x", encoding="utf-8")
        assert "not a directory" in download_dir_problem(config, str(a_file))
        # Checking never changes the setting or creates the folder.
        assert config.get("delivery.download_dir") == before
        assert not (tmp_path / "new").exists()

    def test_dialog_shows_the_default_and_saves_the_choice(
            self, qapp, theme, config, tmp_path):
        from PySide6.QtWidgets import QWidget
        from memanga.config import Config
        from memanga.gui.components.download_location_dialog import (
            CONFIRMED_KEY, DownloadLocationDialog)
        parent = QWidget()
        dialog = DownloadLocationDialog(parent, config)
        assert dialog._path_input.text() == str(config.download_dir)
        assert dialog._path_input.accessibleName() == "Download folder"

        chosen = tmp_path / "Manga"
        dialog._path_input.setText(str(chosen))
        dialog._confirm()

        saved = Config(config.config_dir)
        assert saved.get("delivery.download_dir") == str(chosen)
        assert saved.get(CONFIRMED_KEY) is True

    def test_unusable_folder_keeps_the_dialog_open(self, qapp, theme, config,
                                                   tmp_path):
        from PySide6.QtWidgets import QWidget
        from memanga.gui.components.download_location_dialog import (
            CONFIRMED_KEY, DownloadLocationDialog)
        a_file = tmp_path / "file.txt"
        a_file.write_text("x", encoding="utf-8")
        before = config.get("delivery.download_dir")
        # Kept in a name: Qt deletes a dialog whose parent is collected.
        parent = QWidget()
        dialog = DownloadLocationDialog(parent, config)
        dialog._path_input.setText(str(a_file))
        dialog._confirm()
        assert not dialog._problem.isHidden()
        assert "not a directory" in dialog._problem.text()
        assert config.get("delivery.download_dir") == before
        assert not config.get(CONFIRMED_KEY)

    def test_closing_keeps_the_folder_and_is_not_asked_again(
            self, qapp, theme, config):
        from PySide6.QtWidgets import QWidget
        from memanga.config import Config
        from memanga.gui.components.download_location_dialog import (
            DownloadLocationDialog, needs_download_location)
        before = config.get("delivery.download_dir")
        assert needs_download_location(config)
        parent = QWidget()
        dialog = DownloadLocationDialog(parent, config)
        dialog.reject()
        assert config.get("delivery.download_dir") == before
        assert not needs_download_location(config)
        # Recorded on disk, so the next launch doesn't ask either.
        assert not needs_download_location(Config(config.config_dir))

    def test_first_run_setup_skips_the_dialog_when_not_needed(
            self, gui, config, sample_manga, monkeypatch):
        import memanga.gui.components.download_location_dialog as dialog_mod
        monkeypatch.setattr(
            dialog_mod, "DownloadLocationDialog",
            lambda *a, **k: pytest.fail("dialog opened"))
        config.set("manga", [sample_manga])
        gui._first_run_setup(object(), config)

    def test_first_run_setup_refreshes_what_shows_the_folder(
            self, gui, app_window, monkeypatch, tmp_path):
        import memanga.gui.components.download_location_dialog as dialog_mod
        chosen = str(tmp_path / "Picked")

        class _Dialog:
            def __init__(self, parent, config):
                self._config = config

            def exec(self):
                self._config.set("delivery.download_dir", chosen)
                return 1

        monkeypatch.setattr(dialog_mod, "DownloadLocationDialog", _Dialog)
        app_window.config.set("manga", [])
        gui._first_run_setup(app_window, app_window.config)
        assert app_window._pages["settings"]._dir_entry.text() == chosen


class TestAboutShowsTheDownloadFolder:
    def test_folder_is_shown_and_not_copied(self, app_window, tmp_path):
        from memanga import doctor
        page = app_window._pages["settings"]
        folder = str(tmp_path / "Shelf")
        app_window.config.set("delivery.download_dir", folder)
        page._refresh_about_download_dir()
        assert page._about_download_dir.text() == folder
        assert "Shelf" in page._about_download_dir.accessibleName()
        # Issue #343: copied diagnostics still carry no folder paths.
        assert "Shelf" not in doctor.format_about(doctor.about_basics())
        assert not any(label == "Downloads"
                       for label, _value in doctor.about_rows({}))
