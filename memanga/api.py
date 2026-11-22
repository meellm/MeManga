"""Supported Python API (issue #359).

This module and ``memanga.__version__`` are the only supported Python
interface. Every other module is internal and may change in any release.

The API reads a library; it never changes one. Opening a :class:`Library`
never writes config.yaml or state.json, never repairs a damaged state file,
never creates or moves the config folder and never takes the config
directory lock, so it works while a check or the desktop app is running.
Checks, downloads and edits are done with the command-line interface
(``memanga check``, ``memanga add`` ...), whose exit codes and ``--json``
output are its scripting contract.

Example::

    from memanga.api import Library

    library = Library()          # or Library("/path/to/config-dir")
    for series in library.series(status="reading"):
        print(series.title, series.last_chapter)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

from . import config as _config_mod
from .chapters import chapter_order_key
from .config import Config, explicit_config_dir
from .downloader.sources import _get_sources_from_manga
from .email_settings import kindle_scope, manga_sends_to_kindle
from .state import State

__all__ = ["Library", "LibraryError", "Series", "Source"]


class LibraryError(Exception):
    """The library cannot be read: its config folder does not exist, or
    config.yaml or state.json cannot be loaded or holds a value of the
    wrong type. The message says which folder or file and why; nothing
    was created or changed."""


@dataclass(frozen=True)
class Source:
    """One source of a series: its source name and URL."""
    name: str
    url: str


@dataclass(frozen=True)
class Series:
    """One tracked manga, as it was when the library was (re)loaded."""
    #: Position in the library, the ``#N`` the CLI accepts (1-based).
    position: int
    title: str
    #: "reading", "on-hold", "dropped" or "completed".
    status: str
    #: "auto" or "manual".
    mode: str
    #: Primary source first, then the backup sources.
    sources: Tuple[Source, ...]
    last_chapter: Optional[str]
    #: In chapter order.
    downloaded_chapters: Tuple[str, ...]
    #: Chapters whose download failed and can be retried, in chapter order.
    failed_chapters: Tuple[str, ...]
    send_to_kindle: bool


def _chapters(chapters) -> Tuple[str, ...]:
    return tuple(sorted((str(c) for c in chapters), key=chapter_order_key))


class _Malformed(Exception):
    """A loaded file holds a value of the wrong type."""


def _default_root() -> Path:
    """The default config folder as default_config_dir() picks it, but
    without moving a legacy ~/.config/memanga (issue #249): a library
    that is still there is read in place."""
    native = _config_mod.platform_config_dir()
    legacy = _config_mod.legacy_config_dir()
    if _config_mod.has_config_data(native) or not _config_mod.has_config_data(legacy):
        return native
    return legacy


def _is_chapter(value) -> bool:
    return isinstance(value, (str, int, float)) and not isinstance(value, bool)


def _check_text(where: str, mapping, *keys) -> None:
    for key in keys:
        value = mapping.get(key)
        if value is not None and not isinstance(value, str):
            raise _Malformed(f"{where}: {key} must be text")


def _check_config(config: Config) -> None:
    """Raise _Malformed when a config value the API reads has the wrong
    type, so it never surfaces as a TypeError or KeyError."""
    download_dir = config.get("delivery.download_dir")
    if download_dir is not None and not isinstance(download_dir, str):
        raise _Malformed("delivery.download_dir must be text")
    manga_list = config.get("manga", [])
    if not isinstance(manga_list, list):
        raise _Malformed("manga must be a list")
    for i, manga in enumerate(manga_list, 1):
        if not isinstance(manga, dict):
            raise _Malformed(f"manga #{i} must be a mapping")
        title = manga.get("title")
        if not isinstance(title, str) or not title:
            raise _Malformed(f"manga #{i} has no title")
        where = f"manga #{i} ({title})"
        _check_text(where, manga, "status", "mode", "source", "url")
        sources = manga.get("sources", [])
        if not isinstance(sources, list):
            raise _Malformed(f"{where}: sources must be a list")
        for source in sources:
            if isinstance(source, dict):
                _check_text(f"{where} sources", source, "source", "url")
            elif not isinstance(source, str):
                raise _Malformed(f"{where}: each source must be a URL or a mapping")


def _check_state(state: State, titles) -> None:
    """Raise _Malformed when a state value the API reads for ``titles``
    has the wrong type."""
    manga_state = state.get("manga", {})
    if not isinstance(manga_state, dict):
        raise _Malformed("manga must be a mapping")
    for title in titles:
        # A title with no entry has no state yet; an entry stored as
        # null is a value of the wrong type, not a missing entry.
        if title not in manga_state:
            continue
        entry = manga_state[title]
        where = f"manga {title!r}"
        if not isinstance(entry, dict):
            raise _Malformed(f"{where} must be a mapping")
        last = entry.get("last_chapter")
        if last is not None and not _is_chapter(last):
            raise _Malformed(f"{where}: last_chapter must be a chapter")
        downloaded = entry.get("downloaded", [])
        if not isinstance(downloaded, list) or not all(map(_is_chapter, downloaded)):
            raise _Malformed(f"{where}: downloaded must be a list of chapters")
        if not isinstance(entry.get("failed_chapters", {}), dict):
            raise _Malformed(f"{where}: failed_chapters must be a mapping")


class Library:
    """Read-only view of the library in one config directory.

    ``config_dir`` is chosen as the CLI chooses it: the argument, else
    ``$MEMANGA_CONFIG_DIR``, else the default config folder. Opening and
    reading never create, move, lock or change anything; a library still
    in the legacy ~/.config/memanga folder is read there. Data is read
    once; call :meth:`reload` to see later changes.

    Raises :class:`LibraryError` when the config folder does not exist,
    or config.yaml or state.json cannot be loaded or holds a value of the
    wrong type.
    """

    def __init__(self, config_dir: Union[str, "os.PathLike[str]", None] = None):
        self._explicit_dir = explicit_config_dir(config_dir)
        self.reload()

    @property
    def config_dir(self) -> Path:
        """The config directory this library reads."""
        return self._config_dir

    @property
    def download_dir(self) -> Path:
        """Where chapters are saved (``delivery.download_dir``)."""
        return self._download_dir

    def reload(self) -> None:
        """Read config.yaml and state.json again.

        The default folder is chosen again, so a library the CLI has since
        moved out of the legacy folder is still found. Raises
        :class:`LibraryError` and keeps the previous data when the library
        cannot be read.
        """
        root = self._explicit_dir or _default_root()
        # Config and State create a missing folder; a reader must not.
        if not root.is_dir():
            raise LibraryError(
                f"no MeManga library at {root}: the folder does not exist")
        config = Config(root, tolerate_errors=True)
        if config.load_error:
            raise LibraryError(
                f"cannot load config file {config.config_path}: {config.load_error}")
        try:
            _check_config(config)
        except _Malformed as e:
            raise LibraryError(f"invalid config file {config.config_path}: {e}") from None
        # recover=False: a damaged state.json is only repaired by a
        # process holding the config directory lock (issue #244).
        state = State(root, recover=False)
        if state.load_error:
            raise LibraryError(f"cannot load state file: {state.load_error}")
        manga_list = config.get("manga", [])
        try:
            _check_state(state, [manga["title"] for manga in manga_list])
        except _Malformed as e:
            raise LibraryError(f"invalid state file {state.state_path}: {e}") from None
        scope = kindle_scope(config)
        series = [
            self._make_series(i, manga, state, scope)
            for i, manga in enumerate(manga_list, 1)
        ]
        self._config_dir = root
        self._download_dir = config.download_dir
        self._series = series

    @staticmethod
    def _make_series(position: int, manga, state: State, scope: str) -> Series:
        title = manga["title"]
        sources = tuple(
            Source(name=s.get("source") or "", url=s["url"])
            for s in _get_sources_from_manga(manga) if s.get("url")
        )
        last_chapter = state.get_last_chapter(title)
        return Series(
            position=position,
            title=title,
            status=manga.get("status") or "reading",
            mode=manga.get("mode") or "auto",
            sources=sources,
            last_chapter=None if last_chapter is None else str(last_chapter),
            downloaded_chapters=_chapters(state.get_downloaded_chapters(title)),
            failed_chapters=_chapters(state.get_failed_chapters(title)),
            send_to_kindle=manga_sends_to_kindle(manga, scope),
        )

    def series(self, status: Union[str, Iterable[str], None] = None) -> List[Series]:
        """Tracked manga in library order, optionally only those with
        ``status`` (one status or several)."""
        if status is None:
            return list(self._series)
        wanted = {status} if isinstance(status, str) else set(status)
        return [s for s in self._series if s.status in wanted]

    def get(self, title: str) -> Optional[Series]:
        """The manga titled exactly ``title``, or None."""
        for series in self._series:
            if series.title == title:
                return series
        return None
