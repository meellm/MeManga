"""
Cover image cache with disk persistence and in-memory LRU.
Returns QPixmap for PySide6 GUI.
"""

import hashlib
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtGui import QPixmap, QImage, QColor, QPainter
from PySide6.QtCore import Qt


_MEMORY_LIMIT = 60
_COVERS_DIR_NAME = "covers"


class CoverCache:
    """Caches manga cover images on disk and in memory as QPixmap."""

    def __init__(self, config_dir: Path, event_bus):
        self._disk_dir = config_dir / _COVERS_DIR_NAME
        self._disk_dir.mkdir(parents=True, exist_ok=True)
        self._events = event_bus
        self._memory: OrderedDict[str, QPixmap] = OrderedDict()
        self._loading: set = set()
        self._failed: set = set()
        self._lock = threading.Lock()
        self._placeholders: dict[Tuple[int, int], QPixmap] = {}

    def get_placeholder(self, size: Tuple[int, int]) -> QPixmap:
        if size not in self._placeholders:
            pm = QPixmap(size[0], size[1])
            pm.fill(QColor(20, 25, 32))
            self._placeholders[size] = pm
        return self._placeholders[size]

    def get_cover(self, url: Optional[str], size: Tuple[int, int] = (170, 210)) -> QPixmap:
        if not url:
            return self.get_placeholder(size)

        key = self._cache_key(url, size)

        with self._lock:
            if key in self._memory:
                self._memory.move_to_end(key)
                return self._memory[key]

        disk_path = self._disk_path(url)
        if disk_path.exists():
            try:
                return self._load_and_cache(url, disk_path, size)
            except Exception:
                pass

        with self._lock:
            if url not in self._loading and url not in self._failed:
                self._loading.add(url)
                self._events.publish("cover_fetch_request", {"url": url, "size": size})

        return self.get_placeholder(size)

    def save_to_disk(self, url: str, image_bytes: bytes):
        disk_path = self._disk_path(url)
        try:
            disk_path.write_bytes(image_bytes)
        except Exception:
            pass
        with self._lock:
            self._loading.discard(url)
        self._events.publish("cover_loaded", {"url": url})

    def mark_failed(self, url: str):
        with self._lock:
            self._loading.discard(url)
            self._failed.add(url)

    def _load_and_cache(self, url: str, disk_path: Path, size: Tuple[int, int]) -> QPixmap:
        img = QImage(str(disk_path))
        if img.isNull():
            return self.get_placeholder(size)
        pm = QPixmap.fromImage(img).scaled(
            size[0], size[1], Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Center crop
        if pm.width() > size[0] or pm.height() > size[1]:
            x = (pm.width() - size[0]) // 2
            y = (pm.height() - size[1]) // 2
            pm = pm.copy(x, y, size[0], size[1])

        key = self._cache_key(url, size)
        with self._lock:
            self._memory[key] = pm
            self._memory.move_to_end(key)
            while len(self._memory) > _MEMORY_LIMIT:
                self._memory.popitem(last=False)
        return pm

    def _cache_key(self, url: str, size: Tuple[int, int]) -> str:
        return f"{url}:{size[0]}x{size[1]}"

    def _disk_path(self, url: str) -> Path:
        h = hashlib.md5(url.encode()).hexdigest()
        return self._disk_dir / f"{h}.jpg"
