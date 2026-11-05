"""Tests for the memanga.downloader package layout — the compatibility
import surface, module dependency direction, and browser cleanup
lifecycle after the downloader was split into focused modules."""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

import memanga.downloader as dl

PACKAGE_DIR = Path(dl.__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]

# Every name callers could import from the old single-module downloader,
# mapped to the submodule that now owns it.
LEGACY_NAMES = {
    "restart_browsers": "browsers",
    "_cleanup_at_exit": "browsers",
    "OutputFormat": "chapter",
    "DEFAULT_PAGE_RETRIES": "chapter",
    "download_chapter": "chapter",
    "DownloaderError": "errors",
    "rename_manga_downloads": "folders",
    "UnsafeDownloadPathError": "folders",
    "find_manga_downloads": "folders",
    "delete_manga_downloads": "folders",
    "_image_to_jpeg_bytes": "formats.images",
    "_EPUB_PAGE_TEMPLATE": "formats.epub",
    "_EPUB_CONTAINER_XML": "formats.epub",
    "_images_to_epub": "formats.epub",
    "_images_to_pdf": "formats.pdf",
    "_parse_comicinfo_date": "formats.cbz",
    "_build_comicinfo_xml": "formats.cbz",
    "_images_to_cbz": "formats.cbz",
    "_images_to_folder": "formats.folder",
    "_get_extension": "naming",
    "_sanitize_filename": "naming",
    "_download_folder_key": "naming",
    "_format_chapter_number": "naming",
    "POST_PROCESSING_TIMEOUT": "post_processing",
    "_run_post_processing": "post_processing",
    "_run_post_processing_command": "post_processing",
    "_drain_after_timeout": "post_processing",
    "_POST_PROCESSING_PLACEHOLDER_RE": "post_processing",
    "_substitute_post_processing_placeholders": "post_processing",
    "_split_post_processing_command": "post_processing",
    "_terminate_process_tree": "post_processing",
    "ChapterWithSource": "sources",
    "_configure_mangadex": "sources",
    "_extract_source": "sources",
    "_get_sources_from_manga": "sources",
    "get_supported_sources": "sources",
    "DEFAULT_FALLBACK_DELAY_DAYS": "updates",
    "_max_cached_chapter": "updates",
    "check_for_updates": "updates",
    "_find_chapter_on_backup": "updates",
}


# ─────────────────────────────────────────────────────────────────────────
# Compatibility surface — old imports keep resolving to the real objects
# ─────────────────────────────────────────────────────────────────────────


class TestCompatibilitySurface:
    @pytest.mark.parametrize("name,owner", sorted(LEGACY_NAMES.items()))
    def test_legacy_name_is_reexported_from_owner(self, name, owner):
        module = importlib.import_module(f"memanga.downloader.{owner}")
        assert getattr(dl, name) is getattr(module, name)

    def test_public_names_are_declared(self):
        public = {n for n in LEGACY_NAMES if not n.startswith("_")}
        assert set(dl.__all__) == public

    @pytest.mark.parametrize("name", ["get_scraper", "list_supported_sources"])
    def test_scraper_registry_name_is_reexported(self, name):
        import memanga.scrapers as scrapers
        assert getattr(dl, name) is getattr(scrapers, name)
        assert name not in dl.__all__

    def test_scraper_lookup_seams_use_registry(self):
        # get_scraper is patched where it is looked up, not on the facade.
        import memanga.scrapers as scrapers
        assert dl.updates.get_scraper is scrapers.get_scraper
        assert dl.chapter.get_scraper is scrapers.get_scraper


# ─────────────────────────────────────────────────────────────────────────
# Dependency direction — submodules never import the package facade
# ─────────────────────────────────────────────────────────────────────────


def _submodule_files():
    return sorted(p for p in PACKAGE_DIR.rglob("*.py")
                  if p != PACKAGE_DIR / "__init__.py")


def _package_of(path: Path) -> str:
    """Dotted package a module file belongs to (relative-import anchor)."""
    return ".".join(path.relative_to(REPO_ROOT).parent.parts)


def _rooted_at_package(module: str) -> bool:
    return (module == "memanga.downloader"
            or module.startswith("memanga.downloader."))


class TestDependencyDirection:
    @pytest.mark.parametrize(
        "path", _submodule_files(),
        ids=lambda p: str(p.relative_to(PACKAGE_DIR)))
    def test_submodule_does_not_import_facade(self, path):
        package = _package_of(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # Absolute imports of the package or its submodules would
                # run the facade; siblings are imported relatively.
                for alias in node.names:
                    assert not _rooted_at_package(alias.name), ast.unparse(node)
            elif isinstance(node, ast.ImportFrom):
                if not node.level:
                    assert not _rooted_at_package(node.module or ""), (
                        ast.unparse(node))
                    continue
                base = package.split(".")
                base = base[:len(base) - (node.level - 1)]
                resolved = ".".join(base + ([node.module] if node.module else []))
                if resolved != "memanga.downloader":
                    continue
                # Only `from . import <submodule>` is allowed at this level.
                for alias in node.names:
                    assert ((PACKAGE_DIR / f"{alias.name}.py").exists()
                            or (PACKAGE_DIR / alias.name).is_dir()), (
                        f"{path.name} imports {alias.name!r} from the facade")


# ─────────────────────────────────────────────────────────────────────────
# Browser cleanup lifecycle
# ─────────────────────────────────────────────────────────────────────────


class TestBrowserCleanup:
    def test_import_registers_exit_cleanup_once(self):
        code = (
            "import threading\n"
            "seen = []\n"
            "_register = threading._register_atexit\n"
            "def _record(func, *args, **kwargs):\n"
            "    seen.append((getattr(func, '__module__', ''),\n"
            "                 getattr(func, '__qualname__', '')))\n"
            "    return _register(func, *args, **kwargs)\n"
            "threading._register_atexit = _record\n"
            "import memanga.downloader\n"
            "import memanga.downloader.browsers\n"
            "import importlib; importlib.import_module('memanga.downloader')\n"
            "print(seen.count(('memanga.downloader.browsers',"
            " '_cleanup_at_exit')))\n"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT,
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().splitlines()[-1] == "1"

    def test_exit_closes_started_browsers_on_their_own_threads(self):
        """Issue #235: the interpreter stops worker threads before atexit
        callbacks, so the exit cleanup has to run earlier for a close to
        reach a browser's thread. Real workers and a real interpreter
        exit; the close functions only report where they ran."""
        code = (
            "import sys, threading\n"
            "import memanga.downloader\n"
            "from memanga.scrapers import mangafire as mf\n"
            "from memanga.scrapers import playwright_base as pb\n"
            "def _report(what):\n"
            "    sys.stderr.write(what + ' closed on '\n"
            "                     + threading.current_thread().name + '\\n')\n"
            "pb.cleanup_browsers = lambda: _report('browser')\n"
            "mf.VRFGenerator._close_in_thread = lambda self: _report('vrf')\n"
            "class _Used(pb.PlaywrightScraper):\n"
            "    name = 'used'\n"
            "class _Unused(pb.PlaywrightScraper):\n"
            "    name = 'unused'\n"
            "_Used._run_serialized(lambda: None, timeout=10)\n"
            "mf.get_vrf_generator()\n"
            "mf.VRFGenerator._run_serialized(lambda: None, timeout=10)\n"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT,
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        closed = sorted(result.stderr.splitlines())
        assert len(closed) == 2, result.stderr
        assert closed[0].startswith("browser closed on pw-_Used")
        assert closed[1].startswith("vrf closed on mangafire-vrf")
        assert "_Unused" not in result.stderr

    def test_exit_cleanup_reaches_scraper_hooks_silently(self, monkeypatch,
                                                         capsys):
        import memanga.scrapers.mangafire as mangafire
        from memanga.scrapers.playwright_base import PlaywrightScraper

        calls = []
        monkeypatch.setattr(mangafire, "cleanup_mangafire",
                            lambda: calls.append("mangafire"))
        monkeypatch.setattr(PlaywrightScraper, "cleanup",
                            staticmethod(lambda: calls.append("playwright")))

        dl._cleanup_at_exit()

        assert calls == ["mangafire", "playwright"]
        # Issue #250: exit cleanup must not print (breaks --json output).
        assert capsys.readouterr().out == ""

    def test_restart_browsers_reaches_scraper_hooks(self, monkeypatch):
        import memanga.scrapers.mangafire as mangafire
        from memanga.scrapers.playwright_base import PlaywrightScraper

        calls = []

        class _FakeVRFGenerator:
            def restart(self):
                calls.append("vrf")

        monkeypatch.setattr(mangafire, "VRFGenerator", _FakeVRFGenerator)
        monkeypatch.setattr(PlaywrightScraper, "cleanup",
                            staticmethod(lambda: calls.append("playwright")))

        dl.restart_browsers()

        assert calls == ["vrf", "playwright"]
