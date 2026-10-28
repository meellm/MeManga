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
import xml.etree.ElementTree as ET
import pytest
from pathlib import Path

from PIL import Image


# ─────────────────────────────────────────────────────────────────────────
# Shared fakes
# ─────────────────────────────────────────────────────────────────────────


class FakeState:
    """Minimal State stand-in for download_chapter tests (check_for_updates
    tests use the real ``state`` fixture)."""

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

    def set_chapter_groups(self, title, chapter, source, group_ids, group_names):
        self.chapter_groups = getattr(self, "chapter_groups", {})
        self.chapter_groups[(title, str(chapter))] = {
            "source": source, "group_ids": group_ids, "group_names": group_names}


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
            self, state, patch_get_scraper, monkeypatch):
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
        monkeypatch.setattr(dl.updates, "get_scraper",
                            lambda d: scrapers_by_domain[d])

        manga = {"title": "X", "fallback_delay_days": 2, "sources": [
            {"source": "primary.test", "url": "https://primary.test/x"},
            {"source": "backup.test", "url": "https://backup.test/x"},
        ]}
        new, _ = check_for_updates(manga, state, return_all=True)
        # Ch.4 + Ch.5 only exist on the backup — should be pending,
        # not returned for immediate download.
        new_nums = {c.number for c in new}
        assert "4" not in new_nums or "5" not in new_nums, (
            "backup-only chapter should not be downloaded immediately — "
            "fallback_delay should defer it"
        )

    def test_primary_source_failure_can_still_probe_backup(
            self, state, monkeypatch):
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
        monkeypatch.setattr(dl.updates, "get_scraper", lambda d: scrapers_by_domain[d])

        manga = {"title": "X", "fallback_delay_days": 2, "sources": [
            {"source": "primary.test", "url": "https://primary.test/x"},
            {"source": "backup.test", "url": "https://backup.test/x"},
        ]}

        new, all_ = check_for_updates(manga, state, return_all=True)

        assert new == []
        assert all_ == []
        assert state.get_pending_backup("X", "10") is not None


# ─────────────────────────────────────────────────────────────────────────
# Format conversion functions — each one is a pure file-output helper
# ─────────────────────────────────────────────────────────────────────────


class TestImagesToCbz:
    def test_mangadex_archive_keeps_source_credit(self, jpg_paths, tmp_path):
        from memanga.downloader import _images_to_cbz
        out = tmp_path / "chapter.zip"
        _images_to_cbz(jpg_paths, out, credit="MangaDex · Group A")
        with zipfile.ZipFile(out) as zf:
            assert zf.read("Source.txt").decode("utf-8") == "MangaDex · Group A\n"

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

    def test_mangadex_group_credit_in_comicinfo(self):
        from memanga.downloader import _build_comicinfo_xml
        from memanga.scrapers.base import Chapter
        chapter = Chapter(number="1", url="https://mangadex.org/chapter/abc")
        chapter.group_names = ["Group A", "Group B"]
        fields = self._parse(_build_comicinfo_xml(
            {"title": "Example"}, chapter, page_count=2))
        assert fields["Translator"] == "Group A, Group B"
        assert "Writer" not in fields

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

    def test_unknown_language_and_direction_are_not_claimed(self):
        # Issue #246: no guessed language, reading direction or Count.
        from memanga.downloader import _build_comicinfo_xml
        from memanga.scrapers.base import Chapter
        ch = Chapter(number="5", url="https://x.test/c/5")
        fields = self._parse(_build_comicinfo_xml({"title": "X"}, ch, page_count=1))
        for absent in ("Manga", "LanguageISO", "Count"):
            assert absent not in fields

    @pytest.mark.parametrize("language, expected", [
        ("ja", "ja"), (" pt-BR ", "pt-BR"), ("", None), ("not a tag!", None),
        (None, None), (5, None),
    ])
    def test_language_from_manga_entry(self, language, expected):
        from memanga.downloader import _build_comicinfo_xml
        from memanga.scrapers.base import Chapter
        ch = Chapter(number="5", url="")
        fields = self._parse(_build_comicinfo_xml(
            {"title": "X", "language": language}, ch, page_count=1))
        assert fields.get("LanguageISO") == expected

    @pytest.mark.parametrize("scraper, language, manga_flag", [
        # Jump manga in English: right to left.
        ("memanga.scrapers.tcbscans:TCBScansScraper", "en", "YesAndRightToLeft"),
        # English-only feed; mixes manga and manhwa, so no direction.
        ("memanga.scrapers.mangadex:MangaDexScraper", "en", None),
        # Manhwa/webtoon sites must never be flagged right to left.
        ("memanga.scrapers.asurascans:AsuraScansScraper", None, None),
        ("memanga.scrapers.flamecomics:FlameComicsScraper", None, None),
        # Spanish manhwa site: language known, direction not RTL.
        ("memanga.scrapers.olympus:OlympusScraper", "es", None),
    ])
    def test_source_metadata(self, scraper, language, manga_flag):
        import importlib
        from memanga.downloader import _build_comicinfo_xml
        from memanga.scrapers.base import Chapter
        module, name = scraper.split(":")
        cls = getattr(importlib.import_module(module), name)
        ch = Chapter(number="5", url="")
        fields = self._parse(_build_comicinfo_xml(
            {"title": "X"}, ch, page_count=1, scraper=cls))
        assert fields.get("LanguageISO") == language
        assert fields.get("Manga") == manga_flag

    @pytest.mark.parametrize("entry, manga_flag", [
        ({"reading_direction": "RTL"}, "YesAndRightToLeft"),
        ({"reading_direction": "ltr"}, None),
        ({"reading_direction": "vertical"}, None),
        ({"reading_direction": "sideways"}, "YesAndRightToLeft"),  # invalid: source value
    ])
    def test_manga_entry_direction_overrides_source(self, entry, manga_flag):
        import types as _types
        from memanga.downloader import _build_comicinfo_xml
        from memanga.scrapers.base import Chapter
        source = _types.SimpleNamespace(content_language="en",
                                        reading_direction="rtl")
        fields = self._parse(_build_comicinfo_xml(
            {"title": "X", "language": "fr", **entry}, Chapter(number="1"),
            page_count=1, scraper=source))
        assert fields.get("Manga") == manga_flag
        assert fields["LanguageISO"] == "fr"

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

    def test_mangadex_credit_in_pdf_author(self, jpg_paths, tmp_path):
        pikepdf = pytest.importorskip("pikepdf")
        from memanga.downloader import _images_to_pdf
        out = tmp_path / "ch.pdf"
        _images_to_pdf(jpg_paths, out, credit="MangaDex · Group A")
        with pikepdf.open(out) as pdf:
            assert str(pdf.docinfo["/Author"]) == "MangaDex · Group A"

    def test_undecodable_page_fails_instead_of_being_skipped(
            self, jpg_paths, tmp_path):
        """Issue #229: a bad page used to be skipped with a warning and the
        PDF written anyway, so a chapter missing a page looked complete."""
        from memanga.downloader import _images_to_pdf, DownloaderError
        bad = tmp_path / "page_bad.jpg"
        bad.write_bytes(b"<!DOCTYPE html><html>Just a moment...</html>")
        out = tmp_path / "ch.pdf"
        with pytest.raises(DownloaderError, match="page_bad.jpg"):
            _images_to_pdf([jpg_paths[0], bad, jpg_paths[1]], out)
        assert not out.exists()


_OCF = "urn:oasis:names:tc:opendocument:xmlns:container"
_OPF = "http://www.idpf.org/2007/opf"
_DC = "http://purl.org/dc/elements/1.1/"


class TestImagesToEpub:
    def test_mangadex_credit_in_epub_metadata(self, jpg_paths, tmp_path):
        from memanga.downloader import _images_to_epub
        out = tmp_path / "chapter.epub"
        _images_to_epub(jpg_paths, out, "Example", "1",
                        credit="MangaDex · Group A")
        with zipfile.ZipFile(out) as zf:
            opf = ET.fromstring(zf.read("EPUB/content.opf"))
        meta = opf.find(f"{{{_OPF}}}metadata")
        assert meta.find(f"{{{_DC}}}contributor").text == "MangaDex · Group A"

    def test_author_and_language_metadata(self, jpg_paths, tmp_path):
        # Issue #246: the creator is the author (never the manga title)
        # and the language is the manga's, on the package and every page.
        from memanga.downloader import _images_to_epub
        out = tmp_path / "ch.epub"
        _images_to_epub(jpg_paths, out, "Berserk", "1",
                        author='Kentaro Miura & "Studio"', language="ja")
        with zipfile.ZipFile(out) as zf:
            opf = ET.fromstring(zf.read("EPUB/content.opf"))
            pages = [ET.fromstring(zf.read(n)) for n in zf.namelist()
                     if n.endswith(".xhtml")]
        xml_lang = "{http://www.w3.org/XML/1998/namespace}lang"
        meta = opf.find(f"{{{_OPF}}}metadata")
        assert meta.find(f"{{{_DC}}}creator").text == 'Kentaro Miura & "Studio"'
        assert meta.find(f"{{{_DC}}}language").text == "ja"
        assert opf.get(xml_lang) == "ja"
        assert pages and all(p.get(xml_lang) == "ja" for p in pages)

    def test_no_creator_without_author(self, jpg_paths, tmp_path):
        from memanga.downloader import _images_to_epub
        out = tmp_path / "ch.epub"
        _images_to_epub(jpg_paths, out, title="Berserk", chapter_num="1")
        with zipfile.ZipFile(out) as zf:
            opf = ET.fromstring(zf.read("EPUB/content.opf"))
        meta = opf.find(f"{{{_OPF}}}metadata")
        assert meta.find(f"{{{_DC}}}creator") is None

    def test_unknown_language_is_undetermined(self, jpg_paths, tmp_path):
        # Issue #246: EPUB requires a language; an unknown one is the
        # BCP 47 "und" tag on the package and every page, never English.
        from memanga.downloader import _images_to_epub
        out = tmp_path / "ch.epub"
        _images_to_epub(jpg_paths, out, title="Berserk", chapter_num="1")
        with zipfile.ZipFile(out) as zf:
            opf = ET.fromstring(zf.read("EPUB/content.opf"))
            pages = [ET.fromstring(zf.read(n)) for n in zf.namelist()
                     if n.endswith(".xhtml")]
        xml_lang = "{http://www.w3.org/XML/1998/namespace}lang"
        meta = opf.find(f"{{{_OPF}}}metadata")
        assert meta.find(f"{{{_DC}}}language").text == "und"
        assert opf.get(xml_lang) == "und"
        assert pages and all(p.get(xml_lang) == "und" and p.get("lang") == "und"
                             for p in pages)

    def test_creates_valid_epub(self, jpg_paths, tmp_path):
        from memanga.downloader import _images_to_epub
        out = tmp_path / "ch.epub"
        _images_to_epub(jpg_paths, out, title="X", chapter_num="1")
        assert out.exists()
        with zipfile.ZipFile(out) as zf:
            infos = zf.infolist()
            # OCF: mimetype first, stored uncompressed, exact content.
            assert infos[0].filename == "mimetype"
            assert infos[0].compress_type == zipfile.ZIP_STORED
            assert zf.read("mimetype") == b"application/epub+zip"
            names = zf.namelist()
            assert "META-INF/container.xml" in names
            # Every XML member must be well-formed.
            for name in names:
                if name.endswith((".xml", ".opf", ".xhtml", ".ncx")):
                    ET.fromstring(zf.read(name))
            container = ET.fromstring(zf.read("META-INF/container.xml"))
            rootfile = container.find(f".//{{{_OCF}}}rootfile")
            opf_path = rootfile.get("full-path")
            opf = ET.fromstring(zf.read(opf_path))
            base = opf_path.rsplit("/", 1)[0] + "/"

            # Every manifest href resolves to a real ZIP member.
            manifest = {
                item.get("id"): item
                for item in opf.find(f"{{{_OPF}}}manifest")
            }
            for item in manifest.values():
                assert base + item.get("href") in names

            # Cover falls back to the first page; 3 pages after it.
            spine = [i.get("idref") for i in opf.find(f"{{{_OPF}}}spine")]
            assert spine == ["cover", "page_000", "page_001", "page_002"]
            assert manifest["cover-image"].get("properties") == "cover-image"
            assert any(
                i.get("properties") == "nav" for i in manifest.values()
            )

            meta = opf.find(f"{{{_OPF}}}metadata")
            props = {
                m.get("property"): m.text
                for m in meta.findall(f"{{{_OPF}}}meta") if m.get("property")
            }
            assert props["rendition:layout"] == "pre-paginated"
            assert props["rendition:spread"] == "none"
            assert "dcterms:modified" in props
            assert any(
                m.get("name") == "cover" and m.get("content") == "cover-image"
                for m in meta.findall(f"{{{_OPF}}}meta")
            )
            assert meta.find(f"{{{_DC}}}title").text == "X - Chapter 1"

            # Images are JPEG and pages reference them.
            assert zf.read(base + "images/page_000.jpg")[:2] == b"\xff\xd8"
            page = zf.read(base + "page_000.xhtml").decode()
            assert 'src="images/page_000.jpg"' in page
            assert 'content="width=400, height=600"' in page

    def test_uses_explicit_cover_image(self, jpg_paths, tmp_path):
        from memanga.downloader import _images_to_epub
        cover = tmp_path / "cover.png"
        Image.new("RGBA", (300, 450), (0, 0, 0, 0)).save(cover, "PNG")
        out = tmp_path / "ch.epub"
        _images_to_epub(jpg_paths, out, title="X", chapter_num="1",
                        cover_image_path=cover)
        with zipfile.ZipFile(out) as zf:
            data = zf.read("EPUB/images/cover.jpg")
        with Image.open(io.BytesIO(data)) as img:
            assert img.format == "JPEG"
            assert img.size == (300, 450)

    def test_escapes_title_metadata(self, jpg_paths, tmp_path):
        from memanga.downloader import _images_to_epub
        out = tmp_path / "ch.epub"
        title = 'Tom & Jerry <"Special">'
        _images_to_epub(jpg_paths, out, title=title, chapter_num="1<2>")
        with zipfile.ZipFile(out) as zf:
            opf = ET.fromstring(zf.read("EPUB/content.opf"))
            nav = ET.fromstring(zf.read("EPUB/nav.xhtml"))
            ET.fromstring(zf.read("EPUB/toc.ncx"))
        meta = opf.find(f"{{{_OPF}}}metadata")
        assert meta.find(f"{{{_DC}}}title").text == f"{title} - Chapter 1<2>"
        assert f"{title} - Chapter 1<2>" in "".join(nav.itertext())

    def test_does_not_import_ebooklib(self):
        # EbookLib is AGPL; it must not be pulled into distributed builds.
        import subprocess
        import sys
        code = (
            "import sys, memanga.downloader; "
            "sys.exit(1 if any(m == 'ebooklib' or m.startswith('ebooklib.') "
            "for m in sys.modules) else 0)"
        )
        assert subprocess.run([sys.executable, "-c", code]).returncode == 0

    def test_ebooklib_not_a_declared_dependency(self):
        root = Path(__file__).resolve().parents[2]
        for name in ("pyproject.toml", "requirements.txt",
                     "requirements-docker.txt", "requirements-lock.txt"):
            assert "ebooklib" not in (root / name).read_text().lower(), name


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

    def test_integer_is_zero_padded(self):
        from memanga.downloader import _format_chapter_number
        assert _format_chapter_number("5") == "0005.000"


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
        monkeypatch.setattr(dl.chapter, "get_scraper",
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


class TestMangaDexCredit:
    def test_rebuilt_chapter_takes_group_credit_from_cached_list(
            self, tmp_path, fake_state, monkeypatch):
        """GUI-rebuilt chapters have no group names; the cached chapter
        list from the last check supplies the credit."""
        import memanga.downloader as dl
        url = "https://mangadex.org/chapter/abc"
        fake_state.get_available_chapters = lambda title: [
            {"number": "1", "url": url, "group_names": ["Group A"]}]
        monkeypatch.setattr(dl.chapter, "get_scraper", lambda d: _PartialScraper(2, set()))
        chapter = types.SimpleNamespace(number="1", title="", url=url)
        manga = {"title": "Example", "url": "https://mangadex.org/title/x",
                 "source": "mangadex.org"}
        out = dl.download_chapter(manga, chapter, tmp_path, "zip", fake_state,
                                  max_retries=0)
        with zipfile.ZipFile(out) as zf:
            assert zf.read("Source.txt").decode("utf-8") == "MangaDex · Group A\n"

    def test_saved_chapter_records_its_group(self, tmp_path, fake_state, monkeypatch):
        """The group is stored with the saved chapter, apart from the
        cached chapter list a later check replaces (#400)."""
        import memanga.downloader as dl
        url = "https://mangadex.org/chapter/abc"
        fake_state.get_available_chapters = lambda title: [
            {"number": "1", "url": url, "group_ids": ["g-a"],
             "group_names": ["Group A"]}]
        monkeypatch.setattr(dl.chapter, "get_scraper", lambda d: _PartialScraper(2, set()))
        chapter = types.SimpleNamespace(number="1", title="", url=url)
        manga = {"title": "Example", "url": "https://mangadex.org/title/x",
                 "source": "mangadex.org"}
        dl.download_chapter(manga, chapter, tmp_path, "zip", fake_state,
                            max_retries=0)
        assert fake_state.chapter_groups[("Example", "1")] == {
            "source": "mangadex.org", "group_ids": ["g-a"],
            "group_names": ["Group A"]}

    def test_backup_lookup_skips_removed_group_upload(self, monkeypatch):
        """With the block applied before selection, an allowed duplicate
        is picked instead of the removed group's upload."""
        import memanga.downloader as dl
        from memanga.scrapers.base import Chapter
        from memanga.scrapers.mangadex import MangaDexScraper

        class FakeMangaDex(MangaDexScraper):
            def get_chapters(self, url):
                uploads = [("g-removed", "removed"), ("g-ok", "allowed")]
                out = []
                for group, name in uploads:
                    if group in self.removed_group_ids:
                        continue
                    ch = Chapter(number="5", url=f"https://mangadex.org/chapter/{name}")
                    ch.group_ids = [group]
                    out.append(ch)
                return out

        class FakeConfig:
            def __init__(self, config_dir=None):
                pass

            def get(self, key, default=None):
                return {"mangadex.removed_group_ids": ["g-removed"]}.get(key, default)

        monkeypatch.setattr("memanga.config.Config", FakeConfig)
        monkeypatch.setattr(dl.updates, "get_scraper", lambda d: FakeMangaDex())
        manga = {"title": "Example", "sources": [
            {"source": "mock.test", "url": "https://mock.test/x"},
            {"source": "mangadex.org", "url": "https://mangadex.org/title/x"}]}
        found = dl._find_chapter_on_backup(manga, "5")
        assert found.url == "https://mangadex.org/chapter/allowed"


class TestPartialChapterTolerance:
    def _patch(self, monkeypatch, num_pages, fail_indexes):
        import memanga.downloader as dl
        monkeypatch.setattr(
            dl.chapter, "get_scraper",
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
# Invalid page bytes (issue #229) — a scraper that reports success but
# saved an HTML block page or an empty body is a failed page.
# ─────────────────────────────────────────────────────────────────────────


class _InvalidPageScraper(_PartialScraper):
    """Reports success for every page, but writes ``bodies[idx]`` instead
    of a JPEG for the chosen indexes. ``bad_attempts`` limits how many
    calls per page return the bad body before a real image is served."""

    def __init__(self, num_pages, bodies, bad_attempts=None):
        super().__init__(num_pages, set())
        self._bodies = bodies
        self._bad_attempts = bad_attempts
        self.calls: dict[int, int] = {}

    def download_image(self, url, path):
        idx = int(Path(url).stem[1:])
        self.calls[idx] = self.calls.get(idx, 0) + 1
        if idx in self._bodies and (self._bad_attempts is None
                                    or self.calls[idx] <= self._bad_attempts):
            Path(path).write_bytes(self._bodies[idx])
            return True
        return super().download_image(url, path)


_HTML_PAGE = b"<!DOCTYPE html><html><body>Hotlinking not allowed</body></html>"


def _truncated_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, "JPEG")
    data = buf.getvalue()
    return data[: len(data) // 2]


# Valid JPEG signature, but no image a reader could open.
_CORRUPT_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
_TRUNCATED_JPEG = _truncated_jpeg()

_BAD_BODIES = pytest.mark.parametrize(
    "body", [_HTML_PAGE, b"", _CORRUPT_JPEG, _TRUNCATED_JPEG],
    ids=["html", "empty", "corrupt-jpeg", "truncated-jpeg"])


def _decodes(data: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
        return True
    except Exception:
        return False


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 30), "white").save(buf, "PNG")
    return buf.getvalue()


class TestPageWorkerSessions:
    """Issue #254: page workers never share a requests.Session, and still
    keep the scraper's request spacing."""

    _manga = {"title": "X", "url": "https://cdn.test/x", "source": "cdn.test"}

    def _scraper_class(self, calls, closed, meet):
        import threading
        import requests
        from memanga.scrapers.base import BaseScraper

        body = _png_bytes()
        calls_lock = threading.Lock()

        class _Session(requests.Session):
            def get(self, url, **kwargs):
                with calls_lock:
                    calls.append((self, threading.get_ident()))
                    count = len(calls)
                if count <= 2:
                    # Hold the first two pages until both are in flight.
                    meet.wait()
                response = requests.Response()
                response.status_code = 200
                response._content = body
                response.url = url
                return response

            def close(self):
                closed.append(self)
                super().close()

        class _Scraper(BaseScraper):
            def __init__(self):
                super().__init__()
                self.session = _Session()

            def search(self, query):
                return []

            def get_chapters(self, url):
                return []

            def get_pages(self, url):
                return [f"https://cdn.test/p{i}.png" for i in range(6)]

        return _Scraper

    def test_workers_use_own_sessions_and_shared_spacing(
            self, tmp_path, fake_state, monkeypatch):
        import threading
        import memanga.downloader as dl
        from memanga.downloader import download_chapter
        from memanga.scrapers import base

        calls, closed, sleeps = [], [], []
        meet = threading.Barrier(2, timeout=10)
        lock = threading.Lock()
        now = [100.0]

        def fake_time():
            with lock:
                return now[0]

        def fake_sleep(seconds):
            with lock:
                sleeps.append(seconds)
                now[0] += seconds

        monkeypatch.setattr(base, "time", types.SimpleNamespace(
            time=fake_time, sleep=fake_sleep))
        scraper = self._scraper_class(calls, closed, meet)()
        monkeypatch.setattr(dl.chapter, "get_scraper", lambda d: scraper)

        out = download_chapter(self._manga, _partial_chapter(), tmp_path,
                               "cbz", fake_state, max_retries=0)

        with zipfile.ZipFile(out) as zf:
            assert len([n for n in zf.namelist()
                        if n.startswith("page_")]) == 6
        assert len(calls) == 6
        sessions = {id(s) for s, _ in calls}
        assert id(scraper.session) not in sessions
        assert len(sessions) >= 2
        # One session per worker thread, one worker thread per session.
        threads_of = {}
        sessions_of = {}
        for session, thread in calls:
            threads_of.setdefault(id(session), set()).add(thread)
            sessions_of.setdefault(thread, set()).add(id(session))
        assert all(len(t) == 1 for t in threads_of.values())
        assert all(len(s) == 1 for s in sessions_of.values())
        # Every request after the first waited a full spacing interval.
        assert sleeps == [1.0] * 5
        # Worker sessions are closed with the pool; the scraper's is not.
        assert {id(s) for s in closed} == sessions
        assert scraper.session not in closed

    def test_other_scrapers_are_used_as_they_are(
            self, tmp_path, fake_state, monkeypatch):
        import memanga.downloader as dl
        from memanga.downloader import download_chapter

        used = []

        class _Recording(_PartialScraper):
            def download_image(self, url, path):
                used.append(self)
                return super().download_image(url, path)

        scraper = _Recording(2, set())
        monkeypatch.setattr(dl.chapter, "get_scraper", lambda d: scraper)
        download_chapter(self._manga, _partial_chapter(), tmp_path, "cbz",
                         fake_state, max_retries=0)
        # Test doubles that are not a BaseScraper are not copied.
        assert len(used) == 2 and all(s is scraper for s in used)


class TestInvalidPageBytes:
    _manga = {"title": "X", "url": "https://cdn.test/x", "source": "cdn.test"}

    def _patch(self, monkeypatch, scraper):
        import memanga.downloader as dl
        monkeypatch.setattr(dl.chapter, "get_scraper", lambda d: scraper)
        monkeypatch.setattr(dl.chapter.time, "sleep", lambda s: None)

    @pytest.mark.parametrize("fmt", ["pdf", "cbz", "zip", "epub", "jpg"])
    @_BAD_BODIES
    def test_invalid_page_fails_the_chapter(
            self, tmp_path, fake_state, monkeypatch, fmt, body):
        from memanga.downloader import download_chapter, DownloaderError
        self._patch(monkeypatch, _InvalidPageScraper(4, {2: body}))
        with pytest.raises(DownloaderError) as exc:
            download_chapter(self._manga, _partial_chapter(), tmp_path, fmt,
                             fake_state, max_retries=0)
        assert exc.value.failed_pages == [3]
        assert exc.value.total_pages == 4
        # Nothing was written for the chapter.
        assert not any(p.is_file() for p in tmp_path.rglob("*"))

    @_BAD_BODIES
    def test_invalid_page_is_retried(self, tmp_path, fake_state, monkeypatch,
                                     body):
        from memanga.downloader import download_chapter
        scraper = _InvalidPageScraper(3, {1: body}, bad_attempts=1)
        self._patch(monkeypatch, scraper)
        out = download_chapter(self._manga, _partial_chapter(), tmp_path,
                               "cbz", fake_state, max_retries=2)
        assert scraper.calls[1] == 2
        with zipfile.ZipFile(out) as zf:
            pages = [n for n in zf.namelist() if n.startswith("page_")]
            assert len(pages) == 3
            assert all(_decodes(zf.read(n)) for n in pages)

    @pytest.mark.parametrize("body", [_HTML_PAGE, _CORRUPT_JPEG],
                             ids=["html", "corrupt-jpeg"])
    def test_invalid_page_counts_toward_partial_tolerance(
            self, tmp_path, fake_state, monkeypatch, body):
        from memanga.downloader import download_chapter
        self._patch(monkeypatch, _InvalidPageScraper(10, {4: body}))
        seen = {}
        out = download_chapter(
            self._manga, _partial_chapter(), tmp_path, "zip", fake_state,
            max_retries=0, allow_partial=True, partial_threshold=10,
            on_partial=lambda failed, total: seen.update(failed=failed,
                                                         total=total))
        assert seen == {"failed": [5], "total": 10}
        with zipfile.ZipFile(out) as zf:
            pages = [n for n in zf.namelist() if n.startswith("page_")]
            assert len(pages) == 9
            assert all(_decodes(zf.read(n)) for n in pages)

    def test_invalid_epub_cover_falls_back_to_first_page(
            self, tmp_path, fake_state, monkeypatch):
        from memanga.downloader import download_chapter

        class _BadCoverScraper(_PartialScraper):
            def download_image(self, url, path):
                if "cover" in url:
                    Path(path).write_bytes(_HTML_PAGE)
                    return True
                return super().download_image(url, path)

        self._patch(monkeypatch, _BadCoverScraper(2, set()))
        manga = dict(self._manga, cover_url="https://cdn.test/cover.jpg")
        out = download_chapter(manga, _partial_chapter(), tmp_path, "epub",
                               fake_state, max_retries=0)
        with zipfile.ZipFile(out) as zf:
            assert _decodes(zf.read("EPUB/images/cover.jpg"))


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


class TestFindChapterDownloads:
    """Issue #355: `send TARGET CHAPTER` finds a chapter's saved copies
    only where the downloader writes them, under the names it uses."""

    @staticmethod
    def _find(tmp_path, chapter, **kwargs):
        from memanga.downloader.folders import find_chapter_downloads
        return find_chapter_downloads(tmp_path, "Berserk", chapter, **kwargs)

    @staticmethod
    def _save(tmp_path, name, folder="Berserk"):
        path = tmp_path / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")
        return path

    def test_current_name_with_every_one_file_format(self, tmp_path):
        cbz = self._save(tmp_path, "Berserk - Chapter 0012.000.cbz")
        pdf = self._save(tmp_path, "Berserk - Chapter 0012.000.pdf")
        assert self._find(tmp_path, "12") == [pdf, cbz]

    def test_older_label_forms_are_found(self, tmp_path):
        old = self._save(tmp_path, "Berserk - Chapter 12.pdf")
        part = self._save(tmp_path, "Berserk - Chapter 12.01.epub")
        assert self._find(tmp_path, "12") == [old]
        assert self._find(tmp_path, "12 Part 1") == [part]

    def test_image_folder_is_found(self, tmp_path):
        folder = tmp_path / "Berserk" / "Chapter 0012.000"
        folder.mkdir(parents=True)
        assert self._find(tmp_path, "12") == [folder]

    def test_configured_template_and_source(self, tmp_path):
        custom = self._save(tmp_path, "0012.000 [mangadex.org].pdf")
        found = self._find(tmp_path, "12", templates=["{chapter} [{source}]"],
                           sources=["mangadex.org"])
        assert found == [custom]

    def test_no_loose_matches(self, tmp_path):
        self._save(tmp_path, "Berserk - Chapter 0012.000.pdf")
        self._save(tmp_path, "Berserk - Chapter 1 bonus.pdf")
        assert self._find(tmp_path, "1") == []

    def test_recorded_path_comes_first_only_inside_the_folder(self, tmp_path):
        renamed = self._save(tmp_path, "renamed.pdf")
        current = self._save(tmp_path, "Berserk - Chapter 0012.000.pdf")
        outside = self._save(tmp_path, "elsewhere.pdf", folder="Other")
        nested = self._save(tmp_path, "nested.pdf", folder="Berserk/deeper")
        found = self._find(tmp_path, "12",
                           recorded=[str(outside), str(nested), str(renamed)])
        assert found == [renamed, current]

    def test_symlinked_file_is_never_returned(self, tmp_path):
        target = self._save(tmp_path, "secret.pdf", folder="Other")
        link = tmp_path / "Berserk" / "Berserk - Chapter 0012.000.pdf"
        link.parent.mkdir(parents=True)
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are not available")
        assert self._find(tmp_path, "12", recorded=[str(link)]) == []

    def test_symlinked_manga_folder_is_refused(self, tmp_path):
        from memanga.downloader import UnsafeDownloadPathError
        real = tmp_path / "real"
        self._save(tmp_path, "Berserk - Chapter 0012.000.pdf", folder="real")
        try:
            (tmp_path / "Berserk").symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are not available")
        with pytest.raises(UnsafeDownloadPathError):
            self._find(tmp_path, "12")

    def test_no_download_folder(self, tmp_path):
        assert self._find(tmp_path, "12") == []

    @pytest.mark.parametrize("chapter,other,name", [
        ("2", "2.0", "Berserk - Chapter 2.0.pdf"),
        ("2.0", "2", "Berserk - Chapter 2.0.pdf"),
        ("12 Part 1", "12.01", "Berserk - Chapter 12.01.pdf"),
        ("12.01", "12 Part 1", "Berserk - Chapter 12.01.pdf"),
    ])
    def test_name_another_chapter_could_have_is_left_out(
            self, tmp_path, chapter, other, name):
        shared = self._save(tmp_path, name)
        assert self._find(tmp_path, chapter) == [shared]
        assert self._find(tmp_path, chapter, others=[chapter, other]) == []

    def test_current_name_is_kept_beside_another_chapter(self, tmp_path):
        current = self._save(tmp_path, "Berserk - Chapter 0002.000.pdf")
        self._save(tmp_path, "Berserk - Chapter 2.0.pdf")
        assert self._find(tmp_path, "2", others=["2.0"]) == [current]

    def test_recorded_name_belongs_to_its_chapter(self, tmp_path):
        shared = self._save(tmp_path, "Berserk - Chapter 2.0.pdf")
        assert self._find(tmp_path, "2", others=["2.0"],
                          recorded=[str(shared)]) == [shared]
        assert self._find(tmp_path, "2.0", others=["2"],
                          claimed=[str(shared)]) == []

    def test_name_recorded_for_another_chapter_is_left_out(self, tmp_path):
        renamed = self._save(tmp_path, "renamed.pdf")
        assert self._find(tmp_path, "2", recorded=[str(renamed)],
                          claimed=[str(renamed)]) == []

    def test_no_source_is_always_tried(self, tmp_path):
        bare = self._save(tmp_path, "0012.000 [].pdf")
        assert self._find(tmp_path, "12", templates=["{chapter} [{source}]"],
                          sources=["mangadex.org"]) == [bare]


# ─────────────────────────────────────────────────────────────────────────
# Archive page names follow the page's encoded format, not the URL or temp
# file suffix it was saved under. Pages are generated here with Pillow.
# ─────────────────────────────────────────────────────────────────────────


# Pillow format -> the extension an archive entry must carry.
_ARCHIVE_EXT = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "BMP": ".bmp",
                "TIFF": ".tif", "WEBP": ".webp", "AVIF": ".avif"}


def _encoded(fmt, color=(200, 40, 40), size=(24, 16)) -> bytes:
    """A small image encoded as ``fmt``; skips when this Pillow build
    cannot encode it (only ever asked for WEBP and AVIF)."""
    buf = io.BytesIO()
    try:
        Image.new("RGB", size, color).save(buf, fmt)
    except (KeyError, OSError, ValueError) as e:
        pytest.skip(f"Pillow here cannot encode {fmt}: {e}")
    return buf.getvalue()


def _page_file(tmp_path, name, data) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _decoded_format(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        return img.format


class TestArchivePageNames:
    @pytest.mark.parametrize("fmt,local_name", [
        ("JPEG", "page_000.png"),     # JPEG served from a .png URL
        ("JPEG", "page_000.webp"),
        ("JPEG", "page_000"),         # no suffix at all
        ("JPEG", "page_000.tmp"),
        ("JPEG", "page_000.jpg"),     # matching suffix stays
        ("JPEG", "page_000.jpeg"),    # a JPEG is always named .jpg
        ("PNG", "page_000.jpg"),      # PNG behind a .jpg / default name
        ("PNG", "page_000.png"),
        ("GIF", "page_000.jpg"),
        ("BMP", "page_000.jpg"),
        ("TIFF", "page_000.jpg"),
    ])
    def test_entry_extension_follows_the_bytes(self, tmp_path, fmt,
                                               local_name):
        from memanga.downloader import _images_to_cbz

        data = _encoded(fmt)
        page = _page_file(tmp_path, local_name, data)
        out = tmp_path / "ch.cbz"

        _images_to_cbz([page], out)

        with zipfile.ZipFile(out) as zf:
            (info,) = zf.infolist()
            assert info.filename == f"page_000{_ARCHIVE_EXT[fmt]}"
            assert info.compress_type == zipfile.ZIP_STORED
            assert zf.read(info) == data   # stored exactly, not re-encoded

    @pytest.mark.parametrize("fmt", ["WEBP", "AVIF"])
    def test_encoded_webp_and_avif(self, tmp_path, fmt):
        from memanga.downloader import _images_to_cbz

        data = _encoded(fmt)
        out = tmp_path / "ch.cbz"
        _images_to_cbz([_page_file(tmp_path, "page_000.jpg", data)], out)

        with zipfile.ZipFile(out) as zf:
            assert zf.namelist() == [f"page_000{_ARCHIVE_EXT[fmt]}"]
            assert zf.read(zf.namelist()[0]) == data

    @pytest.mark.parametrize("head,ext", [
        (b"RIFF\x24\x00\x00\x00WEBPVP8 ", ".webp"),
        (b"\x00\x00\x00\x1cftypavif", ".avif"),
        (b"\x00\x00\x00\x1cftypavis", ".avif"),
        (b"\x00\x00\x00\x18ftypheic", ".heic"),
        (b"\x00\x00\x00\x18ftypheix", ".heic"),
    ], ids=["webp", "avif", "avif-sequence", "heic", "heix"])
    def test_formats_named_from_their_signature_alone(self, tmp_path, head,
                                                      ext):
        """The writer reads only the header, so formats this Pillow
        cannot decode (which the page check accepts on their signature)
        are still named correctly."""
        from memanga.downloader import _images_to_cbz

        data = head + b"\x00" * 32
        out = tmp_path / "ch.cbz"
        _images_to_cbz([_page_file(tmp_path, "page_000.jpg", data)], out)

        with zipfile.ZipFile(out) as zf:
            assert zf.namelist() == [f"page_000{ext}"]
            assert zf.read(f"page_000{ext}") == data

    def test_ppm_page_admitted_by_the_page_check_is_archived_as_ppm(
            self, tmp_path):
        """No signature matches PPM; Pillow identifies it (header only)
        and it keeps its own name instead of failing the archive."""
        from memanga.downloader import _images_to_cbz
        from memanga.scrapers.base import is_image_file

        data = _encoded("PPM")
        page = _page_file(tmp_path, "page_000.jpg", data)
        assert is_image_file(page)          # the existing page check
        out = tmp_path / "ch.cbz"

        _images_to_cbz([page], out)

        with zipfile.ZipFile(out) as zf:
            assert zf.namelist() == ["page_000.ppm"]
            assert zf.read("page_000.ppm") == data
            assert _decoded_format(zf.read("page_000.ppm")) == "PPM"

    def test_avif_with_mif1_major_brand_is_archived_as_avif(self, tmp_path):
        """A real, fully decodable AVIF whose ftyp major brand is "mif1"
        (with "avif" among its compatible brands) is not matched by the
        "ftypavif" signature; Pillow identifies it as AVIF."""
        from memanga.downloader import _images_to_cbz
        from memanga.scrapers.base import is_image_file

        data = bytearray(_encoded("AVIF"))
        assert data[4:8] == b"ftyp"
        box_size = int.from_bytes(data[0:4], "big")
        compatible = [bytes(data[i:i + 4]) for i in range(16, box_size, 4)]
        assert b"avif" in compatible, compatible
        data[8:12] = b"mif1"          # same file, major brand mif1
        data = bytes(data)
        assert data[4:12] == b"ftypmif1"
        assert _decoded_format(data) == "AVIF"   # full decode, not a header
        page = _page_file(tmp_path, "page_000.jpg", data)
        assert is_image_file(page)
        out = tmp_path / "ch.cbz"

        _images_to_cbz([page], out)

        with zipfile.ZipFile(out) as zf:
            assert zf.namelist() == ["page_000.avif"]
            assert zf.read("page_000.avif") == data
            assert _decoded_format(zf.read("page_000.avif")) == "AVIF"

    def test_every_canonical_extension_is_advertised(self):
        from memanga.downloader.formats.cbz import (_PAGE_SIGNATURES,
                                                    archive_page_extensions)
        exts = archive_page_extensions()
        assert {ext for ext, _ in _PAGE_SIGNATURES} <= exts
        assert {".ppm", ".jp2"} <= exts

    def test_mixed_pages_keep_order_numbering_bytes_and_metadata(
            self, tmp_path):
        from memanga.downloader import _images_to_cbz

        pages = [("JPEG", "page_000.png"), ("PNG", "page_001.jpg"),
                 ("GIF", "page_002.jpg"), ("BMP", "page_003.png"),
                 ("JPEG", "page_004.jpg")]
        data = [_encoded(fmt, color=(30 * i, 90, 160))
                for i, (fmt, _) in enumerate(pages)]
        paths = [_page_file(tmp_path, name, d)
                 for (_, name), d in zip(pages, data)]
        out = tmp_path / "ch.cbz"

        _images_to_cbz(paths, out, comicinfo_xml=b"<ComicInfo/>",
                       credit="MangaDex · Group A")

        with zipfile.ZipFile(out) as zf:
            assert zf.namelist() == [
                "page_000.jpg", "page_001.png", "page_002.gif",
                "page_003.bmp", "page_004.jpg",
                "ComicInfo.xml", "Source.txt",
            ]
            for i, (fmt, _) in enumerate(pages):
                name = zf.namelist()[i]
                assert zf.read(name) == data[i]
                assert _decoded_format(zf.read(name)) == fmt
                assert zf.getinfo(name).compress_type == zipfile.ZIP_STORED
            assert zf.read("ComicInfo.xml") == b"<ComicInfo/>"
            assert zf.read("Source.txt").decode("utf-8") == "MangaDex · Group A\n"

    def test_unrecognised_page_raises_before_any_archive_is_written(
            self, tmp_path):
        from memanga.downloader import DownloaderError, _images_to_cbz

        paths = [_page_file(tmp_path, "page_000.jpg", _encoded("JPEG")),
                 _page_file(tmp_path, "page_001.jpg",
                            b"<html><body>blocked</body></html>")]
        out = tmp_path / "ch.cbz"

        with pytest.raises(DownloaderError, match=r"Page 2 \(page_001\.jpg\)"):
            _images_to_cbz(paths, out)
        assert not out.exists()

    def test_failure_leaves_an_existing_archive_untouched(self, tmp_path):
        from memanga.downloader import DownloaderError, _images_to_cbz

        out = tmp_path / "ch.cbz"
        _images_to_cbz([_page_file(tmp_path, "good.jpg", _encoded("JPEG"))],
                       out)
        before = out.read_bytes()

        with pytest.raises(DownloaderError):
            _images_to_cbz([_page_file(tmp_path, "bad.png", b"not an image")],
                           out)
        assert out.read_bytes() == before

    def test_missing_page_writes_nothing(self, tmp_path):
        from memanga.downloader import _images_to_cbz

        paths = [_page_file(tmp_path, "page_000.jpg", _encoded("JPEG")),
                 tmp_path / "page_001.jpg"]
        out = tmp_path / "ch.cbz"

        with pytest.raises(FileNotFoundError):
            _images_to_cbz(paths, out)
        assert not out.exists()

    def test_empty_input_raises_and_writes_nothing(self, tmp_path):
        from memanga.downloader import DownloaderError, _images_to_cbz

        out = tmp_path / "ch.cbz"
        with pytest.raises(DownloaderError, match="No images to archive"):
            _images_to_cbz([], out)
        assert not out.exists()


class _FormatScraper:
    """Serves real image bytes of several formats under URLs whose
    extensions lie about them (or have none)."""

    def __init__(self, bodies):
        self.bodies = bodies   # [(url, bytes)]

    def get_pages(self, url):
        return [u for u, _ in self.bodies]

    def download_image(self, url, path):
        Path(path).write_bytes(dict(self.bodies)[url])
        return True

    def get_cover_url(self, url):
        return None


class TestArchiveRoutesNamePagesByFormat:
    """Both public archive outputs (cbz, zip) go through the real
    download_chapter route."""

    _manga = {"title": "X", "url": "https://cdn.test/x", "source": "cdn.test"}

    @pytest.mark.parametrize("output_format", ["cbz", "zip"])
    def test_route_names_entries_by_format(self, tmp_path, fake_state,
                                           monkeypatch, output_format):
        import memanga.downloader as dl

        bodies = [
            ("https://cdn.test/p/0.png", _encoded("JPEG", (10, 20, 30))),
            ("https://cdn.test/p/1.jpg", _encoded("PNG", (40, 50, 60))),
            ("https://cdn.test/p/2", _encoded("GIF", (70, 80, 90))),
            ("https://cdn.test/p/3.jpg?token=x", _encoded("BMP", (5, 6, 7))),
            # Accepted by the page check because Pillow decodes it; named
            # from Pillow's identification, not a signature.
            ("https://cdn.test/p/4.jpg", _encoded("PPM", (8, 9, 10))),
        ]
        monkeypatch.setattr(dl.chapter, "get_scraper",
                            lambda d: _FormatScraper(bodies))
        monkeypatch.setattr(dl.chapter.time, "sleep", lambda s: None)

        out = dl.download_chapter(self._manga, _partial_chapter(), tmp_path,
                                  output_format, fake_state, max_retries=0)

        assert Path(out).suffix == f".{output_format}"
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            pages = [n for n in names if n.startswith("page_")]
            assert pages == ["page_000.jpg", "page_001.png",
                             "page_002.gif", "page_003.bmp",
                             "page_004.ppm"]
            for name, (_, data) in zip(pages, bodies):
                assert zf.read(name) == data
            assert ("ComicInfo.xml" in names) == (output_format == "cbz")

    @pytest.mark.parametrize("output_format", ["cbz", "zip"])
    def test_route_still_rejects_a_non_image_page_first(
            self, tmp_path, fake_state, monkeypatch, output_format):
        """The page check (#229) stops a non-image body before the
        archive writer is reached; nothing is written."""
        import memanga.downloader as dl

        bodies = [("https://cdn.test/p/0.jpg", _encoded("JPEG")),
                  ("https://cdn.test/p/1.jpg", b"<html>blocked</html>")]
        monkeypatch.setattr(dl.chapter, "get_scraper",
                            lambda d: _FormatScraper(bodies))
        monkeypatch.setattr(dl.chapter.time, "sleep", lambda s: None)

        with pytest.raises(dl.DownloaderError):
            dl.download_chapter(self._manga, _partial_chapter(), tmp_path,
                                output_format, fake_state, max_retries=0)
        assert not any(p.is_file() for p in tmp_path.rglob("*"))
