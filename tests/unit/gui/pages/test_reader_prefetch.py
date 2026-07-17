"""
Reader prefetch of the next manual-mode chapter (issue #107).

Covers the setting gate, manual-mode-only behavior, the already-downloaded
skip, worker-level duplicate prevention, reader Next-control refresh after a
prefetch completes, and the cache-miss fallback lookup.
"""

def _setup_manga(app_window, *, mode="manual", available=None,
                 downloaded=None, current="1"):
    """Register a manga on the reader page + seed its cached chapter list
    and downloaded set, returning the reader page ready to prefetch."""
    title = "Prefetch Manga"
    manga = {
        "title": title,
        "url": "https://mock.test/title/pf",
        "source": "mock.test",
        "status": "reading",
        "mode": mode,
        "send_to_kindle": False,
    }
    state = app_window.app_state
    for num in (downloaded or []):
        state.add_downloaded_chapter(title, num)
    if available is not None:
        state.set_available_chapters(title, available)
    page = app_window._pages["reader"]
    page._manga = manga
    page._chapter = current
    return page, title


def _avail(*numbers):
    """Build cached available-chapters entries the resolver understands."""
    return [
        {"number": str(n), "title": f"Ch {n}",
         "url": f"https://mock.test/c/{n}",
         "source": "mock.test",
         "source_url": f"https://mock.test/c/{n}",
         "is_backup": False}
        for n in numbers
    ]


def _capture_downloads(page):
    """Replace worker.download_chapter with a call recorder."""
    calls = []
    page.app.worker.download_chapter = lambda **kw: calls.append(kw)
    return calls


class TestPrefetchGating:
    def test_disabled_by_default_no_prefetch(self, app_window):
        page, _ = _setup_manga(
            app_window, available=_avail(1, 2, 3), downloaded=["1"])
        calls = _capture_downloads(page)
        assert page.app.config.reader_prefetch_enabled is False
        page._maybe_prefetch_next()
        assert calls == []

    def test_auto_mode_never_prefetches(self, app_window):
        app_window.config.set("gui.reader_prefetch_next", True)
        page, _ = _setup_manga(
            app_window, mode="auto", available=_avail(1, 2, 3),
            downloaded=["1"])
        calls = _capture_downloads(page)
        page._maybe_prefetch_next()
        assert calls == []

    def test_manual_mode_prefetches_immediate_next(self, app_window):
        app_window.config.set("gui.reader_prefetch_next", True)
        page, _ = _setup_manga(
            app_window, available=_avail(1, 2, 3), downloaded=["1"])
        calls = _capture_downloads(page)
        page._maybe_prefetch_next()
        assert len(calls) == 1
        assert calls[0]["chapter"].number == "2"

    def test_next_already_downloaded_is_skipped(self, app_window):
        app_window.config.set("gui.reader_prefetch_next", True)
        # Immediate next after ch1 is ch2, which is already on disk.
        page, _ = _setup_manga(
            app_window, available=_avail(1, 2, 3), downloaded=["1", "2"])
        calls = _capture_downloads(page)
        page._maybe_prefetch_next()
        assert calls == []

    def test_stale_cache_forces_lookup_then_prefetches_successor(self, app_window):
        app_window.config.set("gui.reader_prefetch_next", True)
        page, title = _setup_manga(
            app_window, available=_avail(1), downloaded=["1"])
        downloads = _capture_downloads(page)
        checks = []
        page.app.worker.check_updates = lambda *args, **kwargs: checks.append(kwargs)

        page._maybe_prefetch_next()
        page._maybe_prefetch_next()

        assert downloads == []
        assert len(checks) == 1
        assert checks[0]["force"] is True
        assert checks[0]["request_id"] == f"{title}:1"

        page.app.app_state.set_available_chapters(title, _avail(1, 2))
        page._on_check_complete({"results": [], "request_id": f"{title}:1"})

        assert [call["chapter"].number for call in downloads] == ["2"]


class TestDuplicatePrevention:
    def test_worker_drops_duplicate_task_id(self, app_window):
        from memanga.scrapers.base import Chapter
        worker = app_window.worker
        # Pause so submitted jobs sit in the queue where we can count them.
        worker.pause_all()
        manga = {"title": "Dup Manga"}
        ch = Chapter(number="7", title="c7", url="https://mock.test/c/7")
        common = dict(
            manga=manga, chapter=ch, output_dir="/tmp",
            output_format="cbz", state=app_window.app_state)
        worker.download_chapter(**common)
        worker.download_chapter(**common)
        queued = [i for i in worker._download_queue
                  if i["task_id"] == "Dup Manga:7"]
        assert len(queued) == 1

    def test_prefetch_twice_queues_once(self, app_window):
        # End-to-end: two prefetch passes for the same successor must not
        # double-queue (worker cancel-flag dedup backs the reader).
        app_window.config.set("gui.reader_prefetch_next", True)
        app_window.worker.pause_all()
        page, title = _setup_manga(
            app_window, available=_avail(1, 2, 3), downloaded=["1"])
        page._maybe_prefetch_next()
        page._maybe_prefetch_next()
        queued = [i for i in app_window.worker._download_queue
                  if i["task_id"] == f"{title}:2"]
        assert len(queued) == 1


class TestFallbackAndRefresh:
    def test_missing_cache_forces_one_correlated_lookup(self, app_window):
        app_window.config.set("gui.reader_prefetch_next", True)
        page, title = _setup_manga(app_window, downloaded=["1"])
        calls = []
        page.app.worker.check_updates = lambda *args, **kwargs: calls.append(kwargs)

        page._maybe_prefetch_next()
        page._maybe_prefetch_next()

        assert len(calls) == 1
        assert calls[0]["force"] is True
        assert calls[0]["request_id"] == f"{title}:1"

        # An unrelated library check must not consume the in-flight fallback.
        page._on_check_complete({"results": [], "request_id": None})
        assert page._prefetch_fallback_key == f"{title}:1"

    def test_failed_fallback_is_not_retried_for_same_chapter(self, app_window):
        app_window.config.set("gui.reader_prefetch_next", True)
        page, title = _setup_manga(app_window, downloaded=["1"])
        checks = []
        page.app.worker.check_updates = lambda *args, **kwargs: checks.append(kwargs)

        page._maybe_prefetch_next()
        page._on_check_complete({"results": [], "request_id": f"{title}:1"})
        page._maybe_prefetch_next()

        assert len(checks) == 1

    def test_stale_cache_fallback_not_retried_after_empty_completion(self, app_window):
        app_window.config.set("gui.reader_prefetch_next", True)
        page, title = _setup_manga(
            app_window, available=_avail(1), downloaded=["1"])
        checks = []
        page.app.worker.check_updates = lambda *args, **kwargs: checks.append(kwargs)

        page._maybe_prefetch_next()
        page._on_check_complete({"results": [], "request_id": f"{title}:1"})
        page._maybe_prefetch_next()

        assert len(checks) == 1

    def test_matching_fallback_queues_newly_cached_successor(self, app_window):
        app_window.config.set("gui.reader_prefetch_next", True)
        page, title = _setup_manga(app_window, downloaded=["1"])
        page.app.worker.check_updates = lambda *args, **kwargs: None
        downloads = _capture_downloads(page)

        page._maybe_prefetch_next()
        page.app.app_state.set_available_chapters(title, _avail(1, 2))
        page._on_check_complete({"results": [], "request_id": f"{title}:1"})

        assert [call["chapter"].number for call in downloads] == ["2"]

    def test_download_completion_refreshes_next_controls(self, app_window, mocker):
        page, title = _setup_manga(app_window, downloaded=["1"], current="1")
        refresh = mocker.patch.object(page, "_refresh_next_controls")

        page._on_download_complete({"title": "Other", "chapter": "2"})
        refresh.assert_not_called()
        page._on_download_complete({"title": title, "chapter": "2"})
        refresh.assert_called_once_with()


class TestContinuousFooter:
    """Regression: the continuous-mode footer once referenced next_ch,
    which stopped being assigned when Next navigation went dynamic --
    crashing every reader load in the default view mode."""

    def _load_reader(self, app_window, qapp, sample_manga, make_cbz,
                     chapters):
        from pathlib import Path
        title = sample_manga["title"]
        app_window.config.set("manga", [sample_manga])
        dl = Path(app_window.config.download_dir) / title
        dl.mkdir(parents=True, exist_ok=True)
        for n in chapters:
            cbz = make_cbz(pages=2, name="c%s.cbz" % n)
            dest = dl / ("%s - Chapter %s.cbz" % (title, n))
            dest.write_bytes(cbz.read_bytes())
            app_window.app_state.add_downloaded_chapter(title, str(n))
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        return app_window._pages["reader"]

    def test_footer_builds_without_successor(self, app_window, qapp,
                                             sample_manga, make_cbz):
        reader = self._load_reader(
            app_window, qapp, sample_manga, make_cbz, ["1"])
        assert len(reader._images) >= 1
        assert reader._next_footer is not None
        assert reader._next_footer.isHidden()

    def test_footer_labels_downloaded_successor(self, app_window, qapp,
                                                sample_manga, make_cbz):
        reader = self._load_reader(
            app_window, qapp, sample_manga, make_cbz, ["1", "2"])
        assert not reader._next_footer.isHidden()
        assert reader._next_footer_btn.text() == "Next: Chapter 2 >>"

    def test_prefetch_completion_reveals_footer(self, app_window, qapp,
                                                sample_manga, make_cbz):
        reader = self._load_reader(
            app_window, qapp, sample_manga, make_cbz, ["1"])
        title = sample_manga["title"]
        assert reader._next_footer.isHidden()
        # A prefetched chapter 2 lands mid-read.
        app_window.app_state.add_downloaded_chapter(title, "2")
        reader._on_download_complete(dict(title=title, chapter="2"))
        assert not reader._next_footer.isHidden()
        assert not reader._next_btn.isHidden()
        assert reader._next_footer_btn.text() == "Next: Chapter 2 >>"

    def test_prefetch_completion_reveals_labelled_footer(self, app_window,
                                                         qapp, sample_manga,
                                                         make_cbz):
        # A labelled successor like "2 Part 1" must sort after the
        # current "1" in state, or the Next controls stay hidden even
        # though the prefetch downloaded it (issue #107).
        reader = self._load_reader(
            app_window, qapp, sample_manga, make_cbz, ["1"])
        title = sample_manga["title"]
        assert reader._next_footer.isHidden()
        app_window.app_state.add_downloaded_chapter(title, "2 Part 1")
        reader._on_download_complete(dict(title=title, chapter="2 Part 1"))
        assert not reader._next_footer.isHidden()
        assert not reader._next_btn.isHidden()
        assert reader._next_footer_btn.text() == "Next: Chapter 2 Part 1 >>"


class TestOfflineSkip:
    def test_offline_no_ops_prefetch(self, app_window):
        app_window.config.set("gui.reader_prefetch_next", True)
        page, _ = _setup_manga(
            app_window, available=_avail(1, 2, 3), downloaded=["1"])
        calls = _capture_downloads(page)
        checks = []
        page.app.worker.check_updates = lambda *a, **kw: checks.append(kw)
        page.app.worker._is_offline = lambda: True
        page._maybe_prefetch_next()
        assert calls == []
        assert checks == []

    def test_offline_no_ops_fallback_lookup(self, app_window):
        app_window.config.set("gui.reader_prefetch_next", True)
        # No cached chapter list, so the fallback path would fire.
        page, title = _setup_manga(app_window, downloaded=["1"])
        checks = []
        page.app.worker.check_updates = lambda *a, **kw: checks.append(kw)
        page.app.worker._is_offline = lambda: True
        page._maybe_prefetch_next()
        page._maybe_prefetch_fallback(title)
        assert checks == []
        assert page._prefetch_fallback_key is None


class TestSilentFallbackErrors:
    def test_worker_tags_check_error_with_request_id(self, app_window):
        worker = app_window.worker
        worker._is_offline = lambda: True
        seen = []
        app_window.events.subscribe("check_error", lambda d: seen.append(d))
        worker.check_updates(
            [], app_window.app_state, app_window.config,
            force=True, request_id="Prefetch Manga:1")
        app_window.events.poll()
        assert [d.get("request_id") for d in seen] == ["Prefetch Manga:1"]

    def test_app_skips_notification_for_correlated_error(self, app_window):
        before = len(app_window.app_state.get_notifications())
        app_window._on_check_error(
            dict(title="T", error="boom", request_id="T:1"))
        assert len(app_window.app_state.get_notifications()) == before

    def test_app_keeps_notification_for_normal_error(self, app_window):
        before = len(app_window.app_state.get_notifications())
        app_window._on_check_error(dict(title="T", error="boom"))
        assert len(app_window.app_state.get_notifications()) == before + 1

    def test_downloads_toast_skipped_for_correlated_error(self, app_window,
                                                          mocker):
        toast = mocker.patch("memanga.gui.pages.downloads.Toast")
        page = app_window._pages["downloads"]
        page._on_check_error(dict(title="T", error="boom", request_id="T:1"))
        toast.assert_not_called()
        page._on_check_error(dict(title="T", error="boom"))
        toast.assert_called_once()


class TestSilentFallbackCompletions:
    def _result(self, manga, *available):
        import types

        all_chapters = [
            types.SimpleNamespace(
                number=str(n), title=f"Ch {n}", url=f"https://mock.test/c/{n}",
                source=manga.get("source", "mock.test"),
                source_url=f"https://mock.test/c/{n}",
                is_backup=False,
            )
            for n in available
        ]
        return {
            "manga": manga,
            "chapters": all_chapters[-1:],
            "all_chapters": all_chapters,
        }

    def test_app_caches_correlated_completion_without_global_side_effects(
            self, app_window, mocker):
        manga = {
            "title": "Quiet Complete Manga",
            "url": "https://mock.test/title/qc",
            "source": "mock.test",
            "mode": "manual",
        }
        notifications_before = len(app_window.app_state.get_notifications())
        history_before = app_window.app_state.get_check_history()
        added = []
        silent = []
        app_window.events.subscribe("notification_added",
                                    lambda d: added.append(d))
        app_window.events.subscribe("check_complete_silent",
                                    lambda d: silent.append(d))
        refresh = mocker.patch.object(app_window._sidebar, "_refresh_badges")
        sync_done = mocker.patch.object(app_window._sidebar, "_on_check_done")

        app_window.events.publish("check_complete", {
            "results": [self._result(manga, 1, 2)],
            "request_id": f"{manga['title']}:1",
        })
        app_window.events.poll()

        cached = app_window.app_state.get_available_chapters(manga["title"])
        assert [c["number"] for c in cached] == ["1", "2"]
        assert app_window.app_state.get_new_chapters(manga["title"]) == 0
        assert len(app_window.app_state.get_notifications()) == notifications_before
        assert app_window.app_state.get_check_history() == history_before
        assert added == []
        assert silent == []
        refresh.assert_not_called()
        sync_done.assert_not_called()

    def test_sidebar_ignores_correlated_progress_and_completion(
            self, app_window, qapp):
        sidebar = app_window._sidebar
        initial = {
            "status": sidebar._sync_status.text(),
            "counter": sidebar._sync_counter.text(),
            "progress": sidebar._sync_progress.value(),
            "active": sidebar._sync_dot._active,
        }

        app_window.events.publish("check_progress", {
            "current": 1,
            "total": 1,
            "title": "Quiet Complete Manga",
            "request_id": "Quiet Complete Manga:1",
        })
        app_window.events.publish("check_complete", {
            "results": [],
            "request_id": "Quiet Complete Manga:1",
        })
        app_window.events.poll()
        qapp.processEvents()

        assert sidebar._sync_status.text() == initial["status"]
        assert sidebar._sync_counter.text() == initial["counter"]
        assert sidebar._sync_progress.value() == initial["progress"]
        assert sidebar._sync_dot._active == initial["active"] is False

        app_window.events.publish("check_progress", {
            "current": 1,
            "total": 2,
            "title": "Visible Manga",
        })
        app_window.events.poll()

        assert sidebar._sync_status.text() == "Checking…"
        assert sidebar._sync_counter.text() == "1/2"
        assert sidebar._sync_progress.value() == 50
        assert sidebar._sync_dot._active is True

        app_window.events.publish("check_complete", {"results": []})
        app_window.events.poll()
        qapp.processEvents()

        assert sidebar._sync_status.text() == "All caught up"
        assert sidebar._sync_progress.value() == 100
        assert sidebar._sync_dot._active is False


class TestLabelledChapterNumbers:
    def test_prefetch_resolves_labelled_successor(self, app_window):
        app_window.config.set("gui.reader_prefetch_next", True)
        page, _ = _setup_manga(
            app_window, available=_avail("1", "2 Part 1", "Chapter 3"),
            downloaded=["1"])
        calls = _capture_downloads(page)
        page._maybe_prefetch_next()
        assert len(calls) == 1
        assert calls[0]["chapter"].number == "2 Part 1"

    def test_prefetch_resolves_labelled_current_chapter(self, app_window):
        app_window.config.set("gui.reader_prefetch_next", True)
        page, _ = _setup_manga(
            app_window, available=_avail("Chapter 1", "Chapter 2"),
            downloaded=["Chapter 1"], current="Chapter 1")
        calls = _capture_downloads(page)
        page._maybe_prefetch_next()
        assert len(calls) == 1
        assert calls[0]["chapter"].number == "Chapter 2"

    def test_unparseable_current_chapter_skips(self, app_window):
        app_window.config.set("gui.reader_prefetch_next", True)
        page, _ = _setup_manga(
            app_window, available=_avail("1", "2"),
            downloaded=["Extra"], current="Extra")
        calls = _capture_downloads(page)
        page._maybe_prefetch_next()
        assert calls == []


class TestDownloadKwargsPropagation:
    def test_prefetch_uses_configured_delivery_settings(self, app_window):
        cfg = app_window.config
        cfg.set("gui.reader_prefetch_next", True)
        cfg.set("delivery.output_format", "epub")
        cfg.set("delivery.naming_template", "custom-template")
        post = dict(enabled=True, command="echo done", fail_on_error=False)
        cfg.set("delivery.post_processing", post)
        cfg.set("partial_chapters.enabled", True)
        cfg.set("partial_chapters.threshold_percent", 12)
        page, _ = _setup_manga(
            app_window, available=_avail(1, 2), downloaded=["1"])
        calls = _capture_downloads(page)
        page._maybe_prefetch_next()
        assert len(calls) == 1
        call = calls[0]
        assert call["output_format"] == "epub"
        assert call["output_dir"] == cfg.download_dir
        assert call["naming_template"] == "custom-template"
        assert call["post_processing"] == post
        assert call["allow_partial"] is True
        assert call["partial_threshold"] == 12
        assert call["kindle_cfg"] is None
        assert call["state"] is page.app.app_state
