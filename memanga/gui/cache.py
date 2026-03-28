"""
Cover image cache with disk persistence and in-memory LRU.
CTkImage creation is deferred to the main thread (Tkinter requirement).
"""

import hashlib
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Tuple

import customtkinter as ctk
from PIL import Image


_MEMORY_LIMIT = 50
_COVERS_DIR_NAME = "covers"


class CoverCache:
    """Caches manga cover images on disk and in memory."""

    def __init__(self, config_dir: Path, event_bus):
        self._disk_dir = config_dir / _COVERS_DIR_NAME
        self._disk_dir.mkdir(parents=True, exist_ok=True)
        self._events = event_bus
        self._memory: OrderedDict[str, ctk.CTkImage] = OrderedDict()
        self._loading: set = set()
        self._failed: set = set()
        self._lock = threading.Lock()
        self._placeholder: dict[Tuple[int, int], ctk.CTkImage] = {}

    def get_placeholder(self, size: Tuple[int, int]) -> ctk.CTkImage:
        """Get a gray placeholder image for the given size. Must call from main thread."""
        if size not in self._placeholder:
            img = Image.new("RGB", size, color=(60, 60, 80))
            self._placeholder[size] = ctk.CTkImage(
                light_image=img, dark_image=img, size=size,
            )
        return self._placeholder[size]

    def get_cover(self, url: Optional[str], size: Tuple[int, int] = (180, 230)) -> ctk.CTkImage:
        """
        Get a cover image (main thread only).
        Returns cached CTkImage or placeholder. Triggers background fetch if needed.
        """
        if not url:
            return self.get_placeholder(size)

        key = self._cache_key(url, size)

        with self._lock:
            if key in self._memory:
                self._memory.move_to_end(key)
                return self._memory[key]

        # Check disk — create CTkImage here on main thread
        disk_path = self._disk_path(url)
        if disk_path.exists():
            try:
                img = self._load_and_cache(url, disk_path, size)
                return img
            except Exception:
                pass

        # Trigger background fetch (thread-safe)
        with self._lock:
            if url not in self._loading and url not in self._failed:
                self._loading.add(url)
                self._events.publish("cover_fetch_request", {"url": url, "size": size})

        return self.get_placeholder(size)

    def save_to_disk(self, url: str, image_bytes: bytes):
        """Save cover bytes to disk (safe from any thread — no CTkImage created)."""
        disk_path = self._disk_path(url)
        try:
            disk_path.write_bytes(image_bytes)
        except Exception:
            pass

        with self._lock:
            self._loading.discard(url)

        # Signal main thread to load into memory on next get_cover() call
        self._events.publish("cover_loaded", {"url": url})

    def mark_failed(self, url: str):
        """Mark a cover URL as failed so we don't retry indefinitely."""
        with self._lock:
            self._loading.discard(url)
            self._failed.add(url)

    def _load_and_cache(self, url: str, disk_path: Path, size: Tuple[int, int]) -> ctk.CTkImage:
        """Load from disk and cache in memory. Must be called from main thread."""
        pil_img = Image.open(disk_path)
        pil_img = pil_img.convert("RGB")
        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)

        key = self._cache_key(url, size)
        with self._lock:
            self._memory[key] = ctk_img
            self._memory.move_to_end(key)
            while len(self._memory) > _MEMORY_LIMIT:
                self._memory.popitem(last=False)

        return ctk_img

    def _cache_key(self, url: str, size: Tuple[int, int]) -> str:
        return f"{url}:{size[0]}x{size[1]}"

    def _disk_path(self, url: str) -> Path:
        h = hashlib.md5(url.encode()).hexdigest()
        return self._disk_dir / f"{h}.jpg"
