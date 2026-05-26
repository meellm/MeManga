"""End-to-end: Add Manga modal → config write → library refresh.
Download From Chapter modal → state set_last_chapter.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_add_manga_modal_writes_config(app_window, qapp):
    from memanga.gui.pages.add_manga import AddMangaDialog
    d = AddMangaDialog(app_window, app_window)
    d._title_entry.setText("Brand New")
    d._url_entry.setText("https://mangadex.org/title/abc/brand-new")
    # The backup checkbox defaults to True with empty URL — disable.
    d._backup_check.setChecked(False)
    # Stub the worker so check_updates doesn't hit the network.
    app_window.worker.check_updates = lambda *a, **k: None
    d._add_manga()
    titles = [m["title"] for m in app_window.config.get("manga", [])]
    assert "Brand New" in titles


def test_download_from_modal_passes_value_to_callback(app_window, qapp,
                                                        sample_manga):
    from memanga.gui.components.download_from_modal import DownloadFromModal
    seen = []
    m = DownloadFromModal(app_window, sample_manga,
                          on_confirm=lambda start, skip: seen.append((start, skip)))
    m._chapter_input.setText("7")
    m._skip_check.setChecked(True)
    m._do_confirm()
    assert seen == [(7.0, True)]
