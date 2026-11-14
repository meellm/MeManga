"""
Cover image cache with disk persistence and in-memory LRU.
Returns QPixmap for PySide6 GUI.

Memory holds decoded, scaled pixmaps up to a byte budget. Disk holds the
downloaded files up to a size limit (issue #404): past it, the covers
used longest ago are removed. A removed cover is simply fetched again
the next time a card needs it.
"""

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtGui import QGuiApplication, QPixmap, QImage, QColor
from PySide6.QtCore import Qt

from . import theme as T

logger = logging.getLogger(__name__)

_COVERS_DIR_NAME = "covers"

# Decoded pixmaps kept in memory. A count limit (60 before) made any
# library larger than the limit decode its covers from disk again on
# every refresh, on the GUI thread; a byte budget holds a few hundred
# grid covers and still bounds memory on high-density screens, where a
# pixmap is several times larger.
_MEMORY_BUDGET_BYTES = 64 * 1024 * 1024

# Disk limit (`gui.cover_cache_max_mb`). Covers are 30-150 kB each, so
# the default holds a few thousand.
DEFAULT_DISK_LIMIT_MB = 200
MIN_DISK_LIMIT_MB = 10
MAX_DISK_LIMIT_MB = 10_000
# Trimming goes a little below the limit so that it does not run again
# on the very next cover.
_TRIM_TO = 0.9

# A cover in use has its file time renewed at most this often (seconds).
_TOUCH_INTERVAL = 60.0

# Pixmaps are rendered for the screen's device pixel ratio, up to this.
_MAX_PIXEL_RATIO = 3.0


def disk_limit_mb(value) -> int:
    """``gui.cover_cache_max_mb`` as a usable limit: the default for a
    missing or invalid value, otherwise held to the allowed range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_DISK_LIMIT_MB
    return int(max(MIN_DISK_LIMIT_MB, min(MAX_DISK_LIMIT_MB, value)))


def _pixel_ratio() -> float:
    """Device pixel ratio covers are rendered for (1.0 without a screen)."""
    try:
        screen = QGuiApplication.primaryScreen()
        ratio = float(screen.devicePixelRatio()) if screen is not None else 1.0
    except Exception:
        ratio = 1.0
    return max(1.0, min(_MAX_PIXEL_RATIO, ratio))


class CoverCache:
    """Caches manga cover images on disk and in memory as QPixmap."""

    def __init__(self, config_dir: Path, event_bus, max_disk_mb=None):
        self._disk_dir = config_dir / _COVERS_DIR_NAME
        self._disk_dir.mkdir(parents=True, exist_ok=True)
        self._events = event_bus
        self._memory: OrderedDict[str, QPixmap] = OrderedDict()
        self._memory_bytes = 0
        self._loading: set = set()
        self._failed: set = set()
        self._lock = threading.Lock()
        self._placeholders: dict[tuple, QPixmap] = {}
        self._placeholder_keys: set = set()
        # Disk accounting. `_disk_bytes` is a running total, None until
        # the folder has been measured (and again after anything that
        # makes the total uncertain).
        self._disk_lock = threading.Lock()
        self._max_disk_bytes = disk_limit_mb(max_disk_mb) * 1024 * 1024
        self._disk_bytes: Optional[int] = None
        # Cover file -> monotonic time it was last marked used (under
        # `_lock`); spares a file-time update on every repaint.
        self._touched: dict[str, float] = {}

    # ── Placeholder ───────────────────────────────────────────────────

    def get_placeholder(self, size: Tuple[int, int]) -> QPixmap:
        """Flat fill in the current theme's surface colour, shown while
        a cover loads or when there is none."""
        key = (size[0], size[1], T.current_theme())
        if key not in self._placeholders:
            pm = QPixmap(size[0], size[1])
            pm.fill(QColor(T.tokens()["surfaces.bg_2"]))
            self._placeholders[key] = pm
            self._placeholder_keys.add(pm.cacheKey())
        return self._placeholders[key]

    def is_placeholder(self, pixmap) -> bool:
        """Whether ``pixmap`` is one of this cache's placeholders, i.e.
        not a real cover. Widgets with a better placeholder of their own
        (the Library card paints the title) ask this."""
        if pixmap is None or pixmap.isNull():
            return True
        return pixmap.cacheKey() in self._placeholder_keys

    # ── Lookup ────────────────────────────────────────────────────────

    def get_cover(self, url: Optional[str], size: Tuple[int, int] = (170, 210)) -> QPixmap:
        """The cover scaled and center-cropped to ``size`` (in
        device-independent pixels; the pixmap carries the screen's pixel
        ratio), or a placeholder while it is being fetched."""
        if not url:
            return self.get_placeholder(size)

        key = self._cache_key(url, size)

        disk_path = self._disk_path(url)
        with self._lock:
            pm = self._memory.get(key)
            if pm is not None:
                self._memory.move_to_end(key)
        if pm is not None:
            # Shown from memory is still a use: without this, the file of
            # a cover on screen all session aged on disk and the trim
            # removed it ahead of covers nobody had looked at.
            self._mark_used(disk_path)
            return pm

        if disk_path.exists():
            try:
                pm = self._load_and_cache(url, disk_path, size)
                if pm is not None:
                    self._mark_used(disk_path)
                    return pm
                # Cached bytes don't decode as an image (e.g. an HTML
                # block page saved before fetch responses were
                # validated) — drop them and fall through to a fresh
                # fetch request.
                disk_path.unlink(missing_ok=True)
                with self._disk_lock:
                    self._disk_bytes = None
            except Exception:
                pass

        with self._lock:
            if url not in self._loading and url not in self._failed:
                self._loading.add(url)
                self._events.publish("cover_fetch_request", {"url": url, "size": size})

        return self.get_placeholder(size)

    def save_to_disk(self, url: str, image_bytes: bytes):
        """Store a fetched cover. Called from a worker thread.

        A cover larger than the whole disk limit is not stored: kept, it
        would hold the folder over the limit on its own. It is reported
        like a failed download (the card keeps its placeholder, the
        cover is not fetched again this session, and the usual
        replacement lookup may find a smaller one)."""
        with self._disk_lock:
            limit = self._max_disk_bytes
        if len(image_bytes) > limit:
            logger.warning("Cover not cached: %d bytes is more than the "
                           "cover cache limit of %d bytes",
                           len(image_bytes), limit)
            self.mark_failed(url)
            self._events.publish("cover_loaded", {"url": url, "error": True,
                                                  "too_large": True})
            return
        disk_path = self._disk_path(url)
        try:
            previous = disk_path.stat().st_size if disk_path.exists() else 0
            disk_path.write_bytes(image_bytes)
            with self._disk_lock:
                if self._disk_bytes is not None:
                    self._disk_bytes += len(image_bytes) - previous
            self._trim_disk(keep=disk_path)
        except Exception:
            pass
        with self._lock:
            self._loading.discard(url)
        self._events.publish("cover_loaded", {"url": url})

    def mark_failed(self, url: str):
        with self._lock:
            self._loading.discard(url)
            self._failed.add(url)

    # ── Disk limit (issue #404) ───────────────────────────────────────

    @property
    def disk_limit_bytes(self) -> int:
        return self._max_disk_bytes

    def set_disk_limit_mb(self, value) -> None:
        """Change the disk limit and trim to it right away.

        The folder is measured again for this, rather than trusting the
        running total: the total only knows what this object wrote and
        removed, and a limit the user has just chosen has to hold for
        whatever is really in the folder.
        """
        with self._disk_lock:
            self._max_disk_bytes = disk_limit_mb(value) * 1024 * 1024
            self._disk_bytes = None
        self._trim_disk()

    def disk_usage(self) -> int:
        """Bytes the cover files take on disk right now."""
        total = sum(size for _path, size, _mtime in self._disk_files())
        with self._disk_lock:
            self._disk_bytes = total
        return total

    def clear(self) -> int:
        """Remove every cached cover, on disk and in memory. Returns the
        number of files removed."""
        removed = 0
        for path, _size, _mtime in self._disk_files():
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        with self._disk_lock:
            self._disk_bytes = None
        with self._lock:
            self._memory.clear()
            self._memory_bytes = 0
            self._failed.clear()
            self._touched.clear()
        return removed

    def _disk_files(self) -> list:
        """``(path, size, mtime)`` of every file in the cover folder."""
        files = []
        try:
            for entry in os.scandir(self._disk_dir):
                try:
                    if not entry.is_file():
                        continue
                    stat = entry.stat()
                except OSError:
                    continue
                files.append((Path(entry.path), stat.st_size, stat.st_mtime))
        except OSError:
            pass
        return files

    def _trim_disk(self, keep: Optional[Path] = None) -> int:
        """Remove the covers used longest ago until the folder is back
        under the limit. ``keep`` (the cover just saved) goes last, and
        only when it alone is over the limit (the limit was lowered
        while it was being saved); the limit always holds. Returns the
        number of files removed.

        The folder is only listed when the running total says the limit
        is passed, or the total is unknown; a normal save costs nothing
        more than the addition in `save_to_disk`. The total is this
        object's own count of what it wrote; callers that must not rely
        on it (`set_disk_limit_mb`) reset it to unknown first.
        """
        with self._disk_lock:
            limit = self._max_disk_bytes
            if self._disk_bytes is not None and self._disk_bytes <= limit:
                return 0
            files = self._disk_files()
            total = sum(size for _path, size, _mtime in files)
            removed = 0
            if total > limit:
                target = int(limit * _TRIM_TO)
                # Oldest modification time first: `_mark_used` renews it
                # when a cover is shown, so this is least recently used
                # first. The cover just saved is put last.
                order = sorted(files, key=lambda f: (f[0] == keep, f[2]))
                for path, size, _mtime in order:
                    if total <= target:
                        break
                    if path == keep and total <= limit:
                        break  # everything else is gone and it fits
                    try:
                        path.unlink()
                    except OSError:
                        continue
                    total -= size
                    removed += 1
            self._disk_bytes = total
        if removed:
            logger.info("Cover cache over its limit: removed %d least "
                        "recently used cover(s)", removed)
        return removed

    def _mark_used(self, disk_path: Path) -> None:
        """Mark a cover as just used, on disk. The modification time is
        the recency the trim sorts by: access times are often not kept
        (`noatime`, `relatime`).

        Cards ask for their cover on every refresh and repaint, so the
        file is touched at most once per `_TOUCH_INTERVAL`; the order
        of covers used within that time does not matter for the trim."""
        now = time.monotonic()
        key = str(disk_path)
        with self._lock:
            last = self._touched.get(key)
            if last is not None and now - last < _TOUCH_INTERVAL:
                return
            self._touched[key] = now
        try:
            os.utime(disk_path, None)
        except OSError:
            pass  # removed meanwhile: the copy in memory still shows

    # ── Decoding ──────────────────────────────────────────────────────

    def _load_and_cache(self, url: str, disk_path: Path,
                        size: Tuple[int, int]) -> Optional[QPixmap]:
        """Decode the cached file into a scaled QPixmap, or ``None``
        when the bytes aren't a decodable image."""
        img = QImage(str(disk_path))
        if img.isNull():
            return None
        # Rendered at the screen's pixel density and tagged with it, so
        # the cover is sharp on high-density screens and still measures
        # ``size`` in layouts.
        ratio = _pixel_ratio()
        width = max(1, round(size[0] * ratio))
        height = max(1, round(size[1] * ratio))
        img = img.scaled(
            width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Center crop
        if img.width() > width or img.height() > height:
            x = (img.width() - width) // 2
            y = (img.height() - height) // 2
            img = img.copy(x, y, width, height)
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(ratio)

        key = self._cache_key(url, size)
        with self._lock:
            old = self._memory.pop(key, None)
            if old is not None:
                self._memory_bytes -= self._pixmap_bytes(old)
            self._memory[key] = pm
            self._memory_bytes += self._pixmap_bytes(pm)
            # Always keep the newest entry, whatever its size.
            while (self._memory_bytes > _MEMORY_BUDGET_BYTES
                   and len(self._memory) > 1):
                _key, dropped = self._memory.popitem(last=False)
                self._memory_bytes -= self._pixmap_bytes(dropped)
        return pm

    @staticmethod
    def _pixmap_bytes(pixmap: QPixmap) -> int:
        return pixmap.width() * pixmap.height() * 4

    def _cache_key(self, url: str, size: Tuple[int, int]) -> str:
        return f"{url}:{size[0]}x{size[1]}@{_pixel_ratio():g}"

    def _disk_path(self, url: str) -> Path:
        h = hashlib.md5(url.encode()).hexdigest()
        return self._disk_dir / f"{h}.jpg"
