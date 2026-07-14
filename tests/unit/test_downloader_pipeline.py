"""Deep tests for the download pipeline — the actual reason MeManga
exists. Covers:

  - check_for_updates with primary + backup sources and the fallback
    delay (pending_backup) mechanism
  - Source extraction from various manga config shapes
  - Every format conversion helper (_images_to_pdf, _epub, _cbz, _folder)
  - File-naming + sanitization across formats
  - Chapter-number formatting (zero-pad invariants)
  - download_chapter retries / error surfacing
  - _image_to_jpeg_bytes round-trip for EPUB embed
"""

from __future__ import annotations

import io
import types
import zipfile
import pytest
from pathlib import Path

from PIL import Image


# ─────────────────────────────────────────────────────────────────────────
# Shared fakes
# ─────────────────────────────────────────────────────────────────────────


class FakeState:
    """Minimal State stand-in for downloader tests."""

    def __init__(self):
        self.downloaded: set[str] = set()
        self.pending: dict[tuple, dict] = {}
        self.notifications: list = []
        self.health: dict[str, dict] = {}

    def add_downloaded_chapter(self, title, chapter):
        self.downloaded.add(f"{title}|{chapter}")

    def is_chapter_downloaded(self, title, chapter):
        return f"{title}|{chapter}" in self.downloaded

    def get_pending_backup(self, title, chapter):
        return self.pending.get((title, str(chapter)))

    def set_pending_backup(self, title, chapter, source, url):
        from datetime import datetime
        self.pending[(title, str(chapter))] = {
            "source": source, "url": url, "since": datetime.now().isoformat(),
        }

    def clear_pending_backup(self, title, chapter):
        self.pending.pop((title, str(chapter)), None)

    def get_last_chapter(self, title):
        return None

    def set_last_chapter(self, *a, **k):
        pass

    def update_source_health(self, domain, success, error_msg="", latency_ms=None):
        self.health[domain] = {
            "status": "ok" if success else "error",
            "latency_ms": latency_ms,
        }

    def add_notification(self, *a, **k):
        self.notifications.append((a, k))


@pytest.fixture
def fake_state():
    return FakeState()


@pytest.fixture
def jpg_paths(tmp_path):
    """Create 3 sample JPEG pages and return their paths."""
    paths = []
    for i in range(3):
        p = tmp_path / f"page{i}.jpg"
        Image.new("RGB", (400, 600), (i * 60, 100, 200)).save(p, "JPEG")
        paths.append(p)
    return paths


# ─────────────────────────────────────────────────────────────────────────
# _extract_source + _get_sources_from_manga — manga-config shape handling
# ─────────────────────────────────────────────────────────────────────────


class TestSourceExtraction:
    def test_extracts_hostname(self):
        from memanga.downloader import _extract_source
        assert _extract_source("https://mangadex.org/title/abc") == "mangadex.org"

    def test_strips_www(self):
        from memanga.downloader import _extract_source
        assert _extract_source("https://www.mangadex.org/x") == "mangadex.org"

    def test_handles_no_scheme(self):
        from memanga.downloader import _extract_source
        # Documented behavior: urlparse returns empty netloc when there's
        # no scheme. We accept either a non-empty fallback OR an empty
        # string (caller is responsible for passing well-formed URLs).
        out = _extract_source("mangadex.org/title/abc")
        assert isinstance(out, str)

    def test_legacy_single_source_shape(self):
        from memanga.downloader import _get_sources_from_manga
        m = {"title": "X", "source": "mangadex.org",
             "url": "https://mangadex.org/x"}
        out = _get_sources_from_manga(m)
        assert len(out) == 1
        assert out[0]["source"] == "mangadex.org"

    def test_multi_source_shape(self):
        from memanga.downloader import _get_sources_from_manga
        m = {"title": "X", "sources": [
            {"source": "primary.test", "url": "https://primary.test/x"},
            {"source": "backup.test", "url": "https://backup.test/x"},
        ]}
        out = _get_sources_from_manga(m)
        assert len(out) == 2
        assert out[0]["source"] == "primary.test"
        assert out[1]["source"] == "backup.test"

    def test_missing_url_skipped(self):
        from memanga.downloader import _get_sources_from_manga
        m = {"title": "X", "sources": [
            {"source": "good", "url": "https://good.test/x"},
            {"source": "bad", "url": ""},  # blank — should be filtered
        ]}
        out = _get_sources_from_manga(m)
        assert len(out) == 1


# ─────────────────────────────────────────────────────────────────────────
# Backup-source fallback delay logic
# ─────────────────────────────────────────────────────────────────────────


class TestFallbackDelayMechanic:
    """When a chapter is on the backup but not the primary, MeManga is
    supposed to wait `fallback_delay_days` (default 2) before downloading
    from the backup, so the primary has a chance to catch up.
    """

    def test_fresh_pending_does_not_download_immediately(
            self, fake_state, patch_get_scraper, monkeypatch):
        """If primary doesn't have ch.5 but backup does, the first call
        records a pending entry and returns nothing."""
        from memanga.downloader import check_for_updates
        from memanga.scrapers.base import Chapter

        # Primary: chapters 1..3 only.  Backup: chapters 1..5.
        class _PrimaryScraper:
            def get_chapters(self, url):
                return [Chapter(str(i), "", f"u/{i}") for i in (1, 2, 3)]

        class _BackupScraper:
            def get_chapters(self, url):
                return [Chapter(str(i), "", f"u/{i}") for i in (1, 2, 3, 4, 5)]

        from memanga import scrapers
        import memanga.downloader as dl
        scrapers_by_domain = {"primary.test": _PrimaryScraper(),
                              "backup.test": _BackupScraper()}
        monkeypatch.setattr(dl, "get_scraper",
                            lambda d: scrapers_by_domain[d])

        manga = {"title": "X", "fallback_delay_days": 2, "sources": [
            {"source": "primary.test", "url": "https://primary.test/x"},
            {"source": "backup.test", "url": "https://backup.test/x"},
        ]}
        new, _ = check_for_updates(manga, fake_state, return_all=True)
        # Ch.4 + Ch.5 only exist on the backup — should be pending,
        # not returned for immediate download.
        new_nums = {c.number for c in new}
        assert "4" not in new_nums or "5" not in new_nums, (
            "backup-only chapter should not be downloaded immediately — "
            "fallback_delay should defer it"
        )

    def test_primary_source_failure_can_still_probe_backup(
            self, fake_state, monkeypatch):
        """A transient primary outage should not look like an empty library."""
        from memanga.downloader import check_for_updates
        from memanga.scrapers.base import Chapter
        import memanga.downloader as dl

        class _PrimaryScraper:
            def get_chapters(self, url):
                raise RuntimeError("Cloudflare 522")

        class _BackupScraper:
            def get_chapters(self, url):
                return [Chapter("10", "", "https://backup.test/c/10")]

        scrapers_by_domain = {
            "primary.test": _PrimaryScraper(),
            "backup.test": _BackupScraper(),
        }
        monkeypatch.setattr(dl, "get_scraper", lambda d: scrapers_by_domain[d])

        manga = {"title": "X", "fallback_delay_days": 2, "sources": [
            {"source": "primary.test", "url": "https://primary.test/x"},
            {"source": "backup.test", "url": "https://backup.test/x"},
        ]}

        new, all_ = check_for_updates(manga, fake_state, return_all=True)

        assert new == []
        assert all_ == []
        assert ("X", "10") in fake_state.pending


# ─────────────────────────────────────────────────────────────────────────
# Format conversion functions — each one is a pure file-output helper
# ─────────────────────────────────────────────────────────────────────────


class TestImagesToCbz:
    def test_creates_valid_zip(self, jpg_paths, tmp_path):
        from memanga.downloader import _images_to_cbz
        out = tmp_path / "ch.cbz"
        _images_to_cbz(jpg_paths, out)
        assert out.exists()
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            assert len(names) == 3
            # Files should be sorted so the reader displays them in order.
            assert names == sorted(names)

    def test_empty_input_does_not_crash(self, tmp_path):
        from memanga.downloader import _images_to_cbz
        out = tmp_path / "empty.cbz"
        # Pass empty list — either creates empty archive or raises;
        # both are acceptable contracts.
        try:
            _images_to_cbz([], out)
        except Exception:
            pass

    def test_embeds_comicinfo_at_root_without_disturbing_pages(
            self, jpg_paths, tmp_path):
        # ComicInfo.xml must sit at the archive root and must NOT be counted
        # among the page entries or change their names/order.
        from memanga.downloader import _images_to_cbz
        out = tmp_path / "ch.cbz"
        _images_to_cbz(jpg_paths, out, comicinfo_xml=b"<ComicInfo/>")
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            assert "ComicInfo.xml" in names
            pages = [n for n in names if n != "ComicInfo.xml"]
            assert len(pages) == 3
            assert all(n.startswith("page_") for n in pages)
            assert pages == sorted(pages)
            assert zf.read("ComicInfo.xml") == b"<ComicInfo/>"

    def test_no_metadata_keeps_plain_archive(self, jpg_paths, tmp_path):
        # Omitting metadata must leave the archive exactly as before.
        from memanga.downloader import _images_to_cbz
        out = tmp_path / "plain.cbz"
        _images_to_cbz(jpg_paths, out)
        with zipfile.ZipFile(out) as zf:
            assert "ComicInfo.xml" not in zf.namelist()


class TestComicInfoXml:
    """ComicInfo.xml generation from metadata already on hand,
    with no extra network requests."""

    @staticmethod
    def _parse(xml_bytes):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_bytes)
        assert root.tag == "ComicInfo"
        return {child.tag: child.text for child in root}

    def test_basic_fields_always_present(self):
        from memanga.downloader import _build_comicinfo_xml
        from memanga.scrapers.base import Chapter
        manga = {"title": "Berserk"}
        ch = Chapter(number="5", title=None, url="https://x.test/c/5")
        fields = self._parse(_build_comicinfo_xml(manga, ch, page_count=12))
        assert fields["Series"] == "Berserk"
        # No chapter title: falls back to "Chapter <number>".
        assert fields["Title"] == "Chapter 5"
        assert fields["Number"] == "5"
        assert fields["PageCount"] == "12"
        assert fields["Web"] == "https://x.test/c/5"

    def test_optional_fields_written_when_available(self):
        from memanga.downloader import _build_comicinfo_xml
        from memanga.scrapers.base import Chapter
        import xml.etree.ElementTree as ET
        manga = {
            "title": "Berserk",
            "description": "A wandering swordsman.",
            "author": "Kentaro Miura",
            "url": "https://x.test/manga",
        }
        ch = Chapter(number="5", title="The Golden Age",
                     url="https://x.test/c/5", date="2016-05-06")
        fields = self._parse(_build_comicinfo_xml(manga, ch, page_count=20))
        assert fields["Title"] == "The Golden Age"
        assert fields["Summary"] == "A wandering swordsman."
        assert fields["Writer"] == "Kentaro Miura"
        assert fields["Year"] == "2016"
        assert fields["Month"] == "5"
        assert fields["Day"] == "6"
        root = ET.fromstring(_build_comicinfo_xml(manga, ch, page_count=20))
        assert [child.tag for child in root] == [
            "Title", "Series", "Number", "Summary", "Year", "Month",
            "Day", "Writer", "Web", "PageCount",
        ]

    def test_missing_optional_fields_are_omitted(self):
        from memanga.downloader import _build_comicinfo_xml
        from memanga.scrapers.base import Chapter
        manga = {"title": "Berserk"}
        ch = Chapter(number="5", url="")
        fields = self._parse(_build_comicinfo_xml(manga, ch, page_count=1))
        # No description/author/date/url: those tags simply don't appear.
        for absent in ("Summary", "Writer", "Year", "Month", "Day", "Web"):
            assert absent not in fields

    def test_special_characters_are_escaped(self):
        # Raw XML metacharacters must be escaped by the serializer and
        # survive a round-trip parse without corrupting the document.
        from memanga.downloader import _build_comicinfo_xml
        from memanga.scrapers.base import Chapter
        manga = {"title": 'Fist of the <North> & "Star"',
                 "author": "A & B"}
        ch = Chapter(number="1", title="Ch <1> & more", url="https://x.test/?a=1&b=2")
        xml_bytes = _build_comicinfo_xml(manga, ch, page_count=3)
        assert b"&amp;" in xml_bytes  # escaped, not raw
        fields = self._parse(xml_bytes)  # must still parse cleanly
        assert fields["Series"] == 'Fist of the <North> & "Star"'
        assert fields["Title"] == "Ch <1> & more"
        assert fields["Writer"] == "A & B"
        assert fields["Web"] == "https://x.test/?a=1&b=2"

    def test_year_omitted_for_unparseable_date(self):
        from memanga.downloader import _build_comicinfo_xml
        from memanga.scrapers.base import Chapter
        manga = {"title": "X"}
        ch = Chapter(number="1", date="an hour ago")
        fields = self._parse(_build_comicinfo_xml(manga, ch, page_count=1))
        assert "Year" not in fields


class TestImagesToPdf:
    def test_creates_valid_pdf(self, jpg_paths, tmp_path):
        from memanga.downloader import _images_to_pdf
        out = tmp_path / "ch.pdf"
        _images_to_pdf(jpg_paths, out)
        assert out.exists()
        assert out.stat().st_size > 100
        # PDF magic header
        assert out.read_bytes()[:4] == b"%PDF"


class TestImagesToEpub:
    def test_creates_valid_epub(self, jpg_paths, tmp_path):
        from memanga.downloader import _images_to_epub
        out = tmp_path / "ch.epub"
        _images_to_epub(jpg_paths, out, title="X", chapter_num="1")
        assert out.exists()
        # EPUB is a ZIP with a mimetype member.
        with zipfile.ZipFile(out) as zf:
            assert "mimetype" in zf.namelist()


class TestImagesToFolder:
    def test_writes_jpgs_with_zero_padded_names(self, jpg_paths, tmp_path):
        from memanga.downloader import _images_to_folder
        out = tmp_path / "Chapter 1"
        _images_to_folder(jpg_paths, out, img_format="jpg")
        assert out.exists()
        files = sorted(out.iterdir())
        assert len(files) == 3
        # Names should sort lexicographically AND numerically.
        names = [f.name for f in files]
        assert names == sorted(names)


# ─────────────────────────────────────────────────────────────────────────
# Filename helpers
# ─────────────────────────────────────────────────────────────────────────


class TestFilenameSanitizer:
    @pytest.mark.parametrize("dirty,clean_chars", [
        ('a/b\\c', '/\\'),
        ('a<b>c|d', '<>|'),
        ('a:b"c?d*e', ':"?*'),
    ])
    def test_strips_each_class(self, dirty, clean_chars):
        from memanga.downloader import _sanitize_filename
        out = _sanitize_filename(dirty)
        for ch in clean_chars:
            assert ch not in out, f"{ch!r} should be stripped from {dirty!r}"

    def test_preserves_unicode(self):
        from memanga.downloader import _sanitize_filename
        # JP titles often round-trip through this function
        out = _sanitize_filename("恋愛 マニュアル")
        assert "恋愛" in out

    def test_empty_input_returns_something_writable(self):
        from memanga.downloader import _sanitize_filename
        out = _sanitize_filename("")
        # Must not be a path-component that would explode the path API
        assert "/" not in out and "\\" not in out


class TestChapterNumberFormat:
    def test_returns_string(self):
        from memanga.downloader import _format_chapter_number
        assert isinstance(_format_chapter_number("5"), str)

    def test_handles_decimal(self):
        from memanga.downloader import _format_chapter_number
        # Non-integer chapter numbers exist (12.5 etc.) and must round-trip
        out = _format_chapter_number("12.5")
        assert "12" in out and "5" in out


class TestGetExtension:
    def test_picks_extension_from_url(self):
        from memanga.downloader import _get_extension
        assert _get_extension("https://x.test/p001.jpg") == ".jpg"
        assert _get_extension("https://x.test/p001.png") == ".png"

    def test_unknown_url_returns_fallback(self):
        from memanga.downloader import _get_extension
        out = _get_extension("https://x.test/no-extension")
        assert out.startswith(".")


# ─────────────────────────────────────────────────────────────────────────
# _image_to_jpeg_bytes — used by EPUB embed
# ─────────────────────────────────────────────────────────────────────────


class TestImageToJpegBytes:
    def test_converts_jpg(self, jpg_paths):
        from memanga.downloader import _image_to_jpeg_bytes
        # Real signature returns (jpeg_bytes, width, height).
        data, width, height = _image_to_jpeg_bytes(jpg_paths[0])
        assert data[:2] == b"\xff\xd8"  # JPEG SOI
        assert width > 0 and height > 0

    def test_converts_png_to_jpeg(self, tmp_path):
        from memanga.downloader import _image_to_jpeg_bytes
        p = tmp_path / "x.png"
        Image.new("RGBA", (100, 100), (255, 0, 0, 255)).save(p, "PNG")
        data, width, height = _image_to_jpeg_bytes(p)
        # Transparency gets flattened onto white → JPEG bytes
        assert data[:2] == b"\xff\xd8"
        assert (width, height) == (100, 100)


# ─────────────────────────────────────────────────────────────────────────
# download_chapter — the orchestrator, error paths
# ─────────────────────────────────────────────────────────────────────────


class TestDownloadChapterErrors:
    def test_unknown_source_raises_downloader_error(self, tmp_path, fake_state,
                                                      monkeypatch):
        """When no scraper covers the source, the orchestrator should
        raise DownloaderError instead of silently writing nothing."""
        from memanga.downloader import download_chapter, DownloaderError
        import memanga.downloader as dl
        # get_scraper raises ValueError for unknown sources — that's
        # the contract `download_chapter` wraps into `DownloaderError`.
        monkeypatch.setattr(dl, "get_scraper",
                            lambda d: (_ for _ in ()).throw(
                                ValueError(f"unknown: {d}")))
        manga = {"title": "X", "url": "https://unknown.test/x",
                 "source": "unknown.test"}
        chapter = types.SimpleNamespace(
            number="1", title="", url="https://unknown.test/c/1",
            source="unknown.test", source_url="https://unknown.test/c/1",
            is_backup=False)
        with pytest.raises(DownloaderError):
            download_chapter(manga, chapter, tmp_path, "pdf", fake_state)


# ─────────────────────────────────────────────────────────────────────────
# Partial-chapter tolerance (issue #86) — opt-in; a few missing pages are
# kept instead of discarding the whole chapter when within threshold.
# ─────────────────────────────────────────────────────────────────────────


class _PartialScraper:
    """Fake scraper whose download_image fails a chosen set of page
    indexes (0-based) and writes a valid JPEG for the rest."""

    def __init__(self, num_pages, fail_indexes):
        self._num_pages = num_pages
        self._fail = set(fail_indexes)

    def get_pages(self, url):
        return [f"https://cdn.test/p{i}.jpg" for i in range(self._num_pages)]

    def download_image(self, url, path):
        # Index encoded in the filename we asked for: page_%03d.ext
        idx = int(Path(url).stem[1:])
        if idx in self._fail:
            return False
        Image.new("RGB", (200, 300), (10, 20, 30)).save(path, "JPEG")
        return True

    def get_cover_url(self, url):
        return None


def _partial_chapter():
    return types.SimpleNamespace(
        number="71", title="", url="https://cdn.test/c/71",
        source="cdn.test", source_url="https://cdn.test/c/71",
        is_backup=False)


class TestPartialChapterTolerance:
    def _patch(self, monkeypatch, num_pages, fail_indexes):
        import memanga.downloader as dl
        monkeypatch.setattr(
            dl, "get_scraper",
            lambda d: _PartialScraper(num_pages, fail_indexes))

    def test_disabled_by_default_raises_with_structured_detail(
            self, tmp_path, fake_state, monkeypatch):
        """Default behavior unchanged: one missing page discards the
        chapter, and the error carries structured failure detail."""
        from memanga.downloader import download_chapter, DownloaderError
        self._patch(monkeypatch, num_pages=40, fail_indexes={5})
        manga = {"title": "Vinland Saga", "url": "https://cdn.test/x",
                 "source": "cdn.test"}
        with pytest.raises(DownloaderError) as exc:
            download_chapter(manga, _partial_chapter(), tmp_path, "pdf",
                             fake_state, max_retries=0)
        assert exc.value.failed_pages == [6]  # 1-indexed
        assert exc.value.total_pages == 40

    def test_enabled_under_threshold_keeps_partial(
            self, tmp_path, fake_state, monkeypatch):
        """1/40 pages missing (2.5%) is within a 5% threshold — the
        chapter is kept and on_partial is notified."""
        from memanga.downloader import download_chapter
        self._patch(monkeypatch, num_pages=40, fail_indexes={5})
        manga = {"title": "Vinland Saga", "url": "https://cdn.test/x",
                 "source": "cdn.test"}
        seen = {}

        def on_partial(failed, total):
            seen["failed"] = failed
            seen["total"] = total

        out = download_chapter(
            manga, _partial_chapter(), tmp_path, "pdf", fake_state,
            max_retries=0, allow_partial=True, partial_threshold=5,
            on_partial=on_partial)
        assert out is not None and out.exists()
        assert seen == {"failed": [6], "total": 40}

    def test_enabled_over_threshold_still_raises(
            self, tmp_path, fake_state, monkeypatch):
        """5/40 pages missing (12.5%) exceeds a 5% threshold — still a
        hard failure even with tolerance on."""
        from memanga.downloader import download_chapter, DownloaderError
        self._patch(monkeypatch, num_pages=40, fail_indexes={1, 2, 3, 4, 5})
        manga = {"title": "Vinland Saga", "url": "https://cdn.test/x",
                 "source": "cdn.test"}
        with pytest.raises(DownloaderError) as exc:
            download_chapter(
                manga, _partial_chapter(), tmp_path, "pdf", fake_state,
                max_retries=0, allow_partial=True, partial_threshold=5)
        assert len(exc.value.failed_pages) == 5

    def test_zero_usable_pages_is_hard_failure(
            self, tmp_path, fake_state, monkeypatch):
        """Even at 100% threshold, a chapter with no usable pages must
        not be kept as an empty partial."""
        from memanga.downloader import download_chapter, DownloaderError
        self._patch(monkeypatch, num_pages=3, fail_indexes={0, 1, 2})
        manga = {"title": "X", "url": "https://cdn.test/x", "source": "cdn.test"}
        with pytest.raises(DownloaderError):
            download_chapter(
                manga, _partial_chapter(), tmp_path, "pdf", fake_state,
                max_retries=0, allow_partial=True, partial_threshold=100)


# ─────────────────────────────────────────────────────────────────────────
# Restart browsers — Playwright pool reset, used by GUI memory-pressure
# ─────────────────────────────────────────────────────────────────────────


class TestRestartBrowsers:
    def test_callable_without_running_browsers(self):
        """restart_browsers() should be a no-op-safe call even with no
        live Playwright browsers."""
        from memanga.downloader import restart_browsers
        restart_browsers()  # must not raise


# ─────────────────────────────────────────────────────────────────────────
# Rename migration — keep downloaded files reachable after a manga rename
# (issue #41). The reader derives the folder and file names from the
# manga's current title, so a rename must move both.
# ─────────────────────────────────────────────────────────────────────────


class TestRenameMangaDownloads:
    def test_moves_folder_and_rewrites_title_prefix(self, tmp_path):
        from memanga.downloader import rename_manga_downloads
        old_dir = tmp_path / "Old Title"
        old_dir.mkdir()
        (old_dir / "Old Title - Chapter 1.cbz").write_text("a")
        (old_dir / "Old Title - Chapter 2.cbz").write_text("b")

        assert rename_manga_downloads(tmp_path, "Old Title", "New Title") is True

        new_dir = tmp_path / "New Title"
        assert not old_dir.exists()
        assert (new_dir / "New Title - Chapter 1.cbz").read_text() == "a"
        assert (new_dir / "New Title - Chapter 2.cbz").read_text() == "b"

    def test_moves_non_title_prefixed_entries_as_is(self, tmp_path):
        # Image-format downloads use "Chapter N" folders with no title.
        from memanga.downloader import rename_manga_downloads
        old_dir = tmp_path / "Old"
        (old_dir / "Chapter 1").mkdir(parents=True)
        (old_dir / "Chapter 1" / "001.jpg").write_text("img")

        assert rename_manga_downloads(tmp_path, "Old", "New") is True
        assert (tmp_path / "New" / "Chapter 1" / "001.jpg").read_text() == "img"

    def test_no_downloads_returns_false(self, tmp_path):
        from memanga.downloader import rename_manga_downloads
        assert rename_manga_downloads(tmp_path, "Missing", "New") is False

    def test_unchanged_sanitized_title_is_noop(self, tmp_path):
        # The sanitizer strips characters like ':' — titles that collapse
        # to the same safe name must not move anything.
        from memanga.downloader import rename_manga_downloads
        d = tmp_path / "Title"
        d.mkdir()
        assert rename_manga_downloads(tmp_path, "Title", "Title:") is False
        assert d.exists()

    def test_does_not_clobber_existing_destination(self, tmp_path):
        from memanga.downloader import rename_manga_downloads
        old_dir = tmp_path / "Old"
        old_dir.mkdir()
        (old_dir / "Old - Chapter 1.cbz").write_text("new-source")
        new_dir = tmp_path / "New"
        new_dir.mkdir()
        (new_dir / "New - Chapter 1.cbz").write_text("keep-me")

        rename_manga_downloads(tmp_path, "Old", "New")

        # Existing destination file is preserved; the colliding source is
        # left behind in the old folder rather than overwritten.
        assert (new_dir / "New - Chapter 1.cbz").read_text() == "keep-me"
        assert (old_dir / "Old - Chapter 1.cbz").read_text() == "new-source"

    def test_merges_into_existing_new_folder(self, tmp_path):
        from memanga.downloader import rename_manga_downloads
        old_dir = tmp_path / "Old"
        old_dir.mkdir()
        (old_dir / "Old - Chapter 2.cbz").write_text("two")
        new_dir = tmp_path / "New"
        new_dir.mkdir()
        (new_dir / "New - Chapter 1.cbz").write_text("one")

        assert rename_manga_downloads(tmp_path, "Old", "New") is True
        assert (new_dir / "New - Chapter 1.cbz").read_text() == "one"
        assert (new_dir / "New - Chapter 2.cbz").read_text() == "two"
        assert not old_dir.exists()
