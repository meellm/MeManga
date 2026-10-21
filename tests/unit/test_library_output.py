"""Library code reports through logging, never stdout (issue #226).

stdout belongs to command results (`--json` payloads, `memanga path`);
a stray print() from a scraper or the downloader corrupts it and can't
be silenced or redirected.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

import memanga

PACKAGE = Path(memanga.__file__).parent

# Modules that run under the CLI or the GUI's background workers.
LIBRARY_PATHS = [
    "scrapers",
    "downloader",
    "emailer.py",
    "chapter_pipeline.py",
    "search.py",
    "gui/workers.py",
    "gui/app.py",
    "gui/events.py",
    "gui/download_events.py",
]


def _python_files():
    for rel in LIBRARY_PATHS:
        path = PACKAGE / rel
        if path.is_dir():
            yield from sorted(path.rglob("*.py"))
        else:
            yield path


def _print_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id == "print"]


def test_library_modules_do_not_print():
    offenders = {
        str(path.relative_to(PACKAGE)): lines
        for path in _python_files()
        if (lines := _print_calls(path))
    }
    assert offenders == {}, (
        "use logging.getLogger(__name__) instead of print(): "
        f"{offenders}")


def test_source_fetch_failure_is_a_warning_not_stdout(state, capsys, caplog,
                                                      monkeypatch):
    from memanga.downloader import DownloaderError, updates

    def _broken(source):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(updates, "get_scraper", _broken)
    manga = {"title": "Alpha", "source": "example.org",
             "url": "https://example.org/alpha", "status": "reading"}

    with caplog.at_level(logging.DEBUG, logger="memanga"):
        with pytest.raises(DownloaderError):
            updates.check_for_updates(manga, state)

    assert capsys.readouterr().out == ""
    records = [r for r in caplog.records
               if r.name == "memanga.downloader.updates"]
    assert [r.levelno for r in records] == [logging.WARNING]
    assert "Failed to fetch from example.org: connection reset" in records[0].getMessage()


def test_page_download_failure_is_debug_not_stdout(tmp_path, capsys, caplog,
                                                   monkeypatch):
    from memanga.scrapers.kaijuno8manga import KaijuNo8MangaScraper

    scraper = KaijuNo8MangaScraper()

    def _fail(*args, **kwargs):
        raise OSError("timed out")
    monkeypatch.setattr(scraper.session, "get", _fail)

    with caplog.at_level(logging.DEBUG, logger="memanga"):
        assert scraper.download_image("https://cdn.example/1.jpg",
                                      tmp_path / "1.jpg") is False

    assert capsys.readouterr().out == ""
    records = [r for r in caplog.records
               if r.name == "memanga.scrapers.kaijuno8manga"]
    assert [r.levelno for r in records] == [logging.DEBUG]
    assert "https://cdn.example/1.jpg" in records[0].getMessage()
