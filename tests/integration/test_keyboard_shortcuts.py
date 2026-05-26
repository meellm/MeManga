"""Tests for the global Cmd/Ctrl+K shortcut + reader keyboard nav."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_cmd_k_shortcut_registered(app_window):
    assert hasattr(app_window, "_search_shortcut")


def test_focus_search_navigates_and_focuses(app_window, qapp):
    app_window._focus_search()
    qapp.processEvents()
    assert app_window._current_page == "search"
