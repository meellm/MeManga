"""
Lazy page loading for the reader (issue #389).

Opening a chapter only *indexes* it: page order plus each page's natural
size, read from the image headers. Pixels are decoded per page on demand,
on a small worker pool, and only for the pages around the reading
position. The reader keeps a bounded cache of the scaled results.

Thread rules (Qt): QImage may be created and scaled on any thread; QPixmap
only on the GUI thread. Workers therefore hand QImages back through a
queued signal, and PixmapCache is touched from the GUI thread only.
"""

from __future__ import annotations

import logging
import threading
import zipfile
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import (QBuffer, QByteArray, QIODevice, QObject, QSize,
                            Qt, Signal)
from PySide6.QtGui import QImage, QImageReader, QPixmap

logger = logging.getLogger(__name__)

# Every extension the archive writer can name a page with
# (downloader/formats/cbz.py); Qt's content probe below still decides
# whether a page is actually readable.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif",
                    ".bmp", ".tif", ".tiff", ".avif", ".heic")

# Enough to reach the size field of every supported format, including
# JPEGs with large EXIF/ICC segments. Rarer cases fall back to the whole
# entry.
_HEADER_BYTES = 64 * 1024

# Same render resolution the reader has always used for PyMuPDF pages.
_PDF_DPI = 150

# Backend kinds a PageRef can name.
KIND_ZIP = "zip"
KIND_IMAGE = "image"
KIND_PDF_FITZ = "pdf-fitz"
KIND_PDF_PIKEPDF = "pdf-pikepdf"


@dataclass(frozen=True)
class PageRef:
    """Where one page lives and its natural size. Holds no pixels."""

    source: Path
    kind: str
    member: str = ""
    page: int = 0
    width: int = 0
    height: int = 0


# ── Indexing (header reads only) ─────────────────────────────────────────


def _probe_size(device) -> Optional[Tuple[int, int]]:
    """Natural size of the image on *device*, read from its header.

    None when Qt can't read it as an image at all; (0, 0) when it is an
    image whose size the header doesn't give away."""
    reader = QImageReader(device)
    if not reader.canRead():
        return None
    size = reader.size()
    if not size.isValid():
        return (0, 0)
    return (size.width(), size.height())


def _probe_bytes(data: bytes) -> Optional[Tuple[int, int]]:
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    try:
        return _probe_size(buf)
    finally:
        buf.close()


@lru_cache(maxsize=1)
def archive_member_extensions() -> frozenset:
    """Extensions of archive members that may be pages: the common image
    extensions plus every one MeManga's archive writer can name a page
    with (Pillow-identified formats such as .ppm included)."""
    from ...downloader.formats.cbz import archive_page_extensions
    return frozenset(IMAGE_EXTENSIONS) | archive_page_extensions()


def _index_zip(filepath: Path, names: Iterable[str]) -> List[PageRef]:
    pages = []
    accepted = archive_member_extensions()
    with zipfile.ZipFile(filepath, "r") as zf:
        for name in names:
            if Path(name).suffix.lower() not in accepted:
                continue
            with zf.open(name) as fh:
                head = fh.read(_HEADER_BYTES)
            size = _probe_bytes(head)
            if size == (0, 0) and len(head) >= _HEADER_BYTES:
                size = _probe_bytes(zf.read(name))
            if size is None:
                continue
            pages.append(PageRef(filepath, KIND_ZIP, member=name,
                                 width=size[0], height=size[1]))
    return pages


def _index_pdf(filepath: Path) -> List[PageRef]:
    try:
        import fitz
    except ImportError:
        fitz = None
    if fitz is not None:
        pages = []
        zoom = _PDF_DPI / 72
        doc = fitz.open(str(filepath))
        try:
            for i, page in enumerate(doc):
                rect = page.rect * fitz.Matrix(zoom, zoom)
                irect = rect.irect
                pages.append(PageRef(filepath, KIND_PDF_FITZ, page=i,
                                     width=irect.width, height=irect.height))
        finally:
            doc.close()
        return pages

    import pikepdf
    pages = []
    with pikepdf.open(str(filepath)) as pdf:
        for i, page in enumerate(pdf.pages):
            for img_key in page.images:
                raw = page.images[img_key]
                try:
                    width = int(raw.get("/Width", 0))
                    height = int(raw.get("/Height", 0))
                except Exception:
                    width = height = 0
                pages.append(PageRef(filepath, KIND_PDF_PIKEPDF,
                                     member=str(img_key), page=i,
                                     width=width, height=height))
    return pages


def index_chapter_file(filepath: Path) -> List[PageRef]:
    """Pages of a downloaded chapter file, in reading order."""
    suffix = filepath.suffix.lower()
    try:
        if suffix in (".cbz", ".zip"):
            with zipfile.ZipFile(filepath, "r") as zf:
                names = sorted(n for n in zf.namelist()
                               if not n.startswith("__"))
            return _index_zip(filepath, names)
        if suffix == ".pdf":
            return _index_pdf(filepath)
        if suffix == ".epub":
            with zipfile.ZipFile(filepath, "r") as zf:
                names = sorted(zf.namelist())
            return _index_zip(filepath, names)
    except Exception as e:
        logger.warning("Couldn't index chapter %s: %s", filepath, e)
        logger.debug("Chapter index traceback", exc_info=True)
    return []


def index_chapter_folder(folder: Path) -> List[PageRef]:
    """Pages of an image-folder chapter, in reading order."""
    pages = []
    files = sorted(f for f in folder.iterdir()
                   if f.suffix.lower() in IMAGE_EXTENSIONS)
    for f in files:
        try:
            size = _probe_size(str(f))
        except Exception:
            size = None
        if size is None:
            continue
        pages.append(PageRef(f, KIND_IMAGE, width=size[0], height=size[1]))
    return pages


# ── Decoding (worker threads) ────────────────────────────────────────────


# Pillow modes whose pixel bytes QImage takes as they are.
_PIL_QT_FORMATS = {
    "L": QImage.Format.Format_Grayscale8,
    "RGB": QImage.Format.Format_RGB888,
    "RGBA": QImage.Format.Format_RGBA8888,
}


def _is_plain_jpeg(pdf_image) -> bool:
    """True when the PDF image stream is a standard JPEG file as stored:
    a lone DCTDecode filter, gray or YCbCr-coded RGB, and no /Decode
    remap — the cases any JPEG reader shows correctly. A colour space
    pikepdf has no mode for (CalRGB, ...) still gets the direct try: the
    JPEG's own header says how to read it."""
    if pdf_image.filters != ["/DCTDecode"]:
        return False
    if "/Decode" in pdf_image.obj:
        return False
    try:
        mode = pdf_image.mode
    except NotImplementedError:
        mode = None
    if mode == "L":
        return True
    if mode not in ("RGB", None):
        return False
    parms = pdf_image.filter_decodeparms[0][1]
    transform = 1 if parms is None else parms.get("/ColorTransform", 1)
    return int(transform) == 1


def _qimage_from_pil(pil_img) -> QImage:
    """Copy a Pillow image's pixels into a QImage, without re-encoding."""
    try:
        if pil_img.mode not in _PIL_QT_FORMATS:
            alpha = (pil_img.mode in ("LA", "La", "PA", "RGBa")
                     or "transparency" in pil_img.info)
            target = "RGBA" if alpha else ("L" if pil_img.mode == "1"
                                           else "RGB")
            converted = pil_img.convert(target)
            pil_img.close()
            pil_img = converted
        width, height = pil_img.size
        data = pil_img.tobytes()
        img = QImage(data, width, height,
                     width * len(pil_img.getbands()),
                     _PIL_QT_FORMATS[pil_img.mode])
        # Deep copy: QImage doesn't own *data*.
        return img.copy()
    finally:
        pil_img.close()


def _decode_pdf_image(raw) -> QImage:
    """One embedded PDF image, decoded without PyMuPDF.

    A plain JPEG stream goes to QImage as stored. Anything else is
    unpacked by pikepdf (filters, palettes, colour spaces) and its pixels
    copied straight into a QImage — never re-encoded to another format."""
    import pikepdf
    pdf_image = pikepdf.PdfImage(raw)
    if _is_plain_jpeg(pdf_image):
        img = QImage()
        if img.loadFromData(raw.read_raw_bytes()):
            return img
    img = _qimage_from_pil(pdf_image.as_pil_image())
    if img.isNull():
        raise ValueError(f"unsupported PDF image {pdf_image!r}")
    return img


def _decode(ref: PageRef) -> QImage:
    if ref.kind == KIND_ZIP:
        with zipfile.ZipFile(ref.source, "r") as zf:
            data = zf.read(ref.member)
        img = QImage()
        img.loadFromData(data)
        return img
    if ref.kind == KIND_IMAGE:
        return QImage(str(ref.source))
    if ref.kind == KIND_PDF_FITZ:
        import fitz
        doc = fitz.open(str(ref.source))
        try:
            pix = doc[ref.page].get_pixmap(dpi=_PDF_DPI)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format.Format_RGB888)
            # Deep copy: pix.samples is transient.
            return img.copy()
        finally:
            doc.close()
    if ref.kind == KIND_PDF_PIKEPDF:
        import pikepdf
        with pikepdf.open(str(ref.source)) as pdf:
            return _decode_pdf_image(pdf.pages[ref.page].images[ref.member])
    return QImage()


def decode_page(ref: PageRef) -> QImage:
    """Decode one page at full resolution. Null image on failure, which
    is logged as a warning with its cause.

    Each call opens and closes its own handle, so concurrent decodes never
    share a file object and no handle outlives the call."""
    where = ref.member or ref.page
    try:
        img = _decode(ref)
    except Exception as e:
        logger.warning("Couldn't decode reader page %s (%s): %s",
                       ref.source, where, e)
        logger.debug("Reader page decode traceback", exc_info=True)
        return QImage()
    if img.isNull():
        logger.warning("Couldn't decode reader page %s (%s): not a "
                       "readable image", ref.source, where)
    return img


def display_size(width: int, height: int, target_w: int,
                 zoom: float) -> QSize:
    """On-screen size of a page: shrink to *target_w* when wider, else
    scale by *zoom* — the rule the reader has always used. Computed with
    QSize.scaled so it equals what QImage.scaled(KeepAspectRatio) yields."""
    if width > target_w:
        ratio = target_w / width
        new_w, new_h = int(width * ratio), int(height * ratio)
    else:
        new_w, new_h = int(width * zoom), int(height * zoom)
    new_w, new_h = max(1, new_w), max(1, new_h)
    return QSize(width, height).scaled(
        new_w, new_h, Qt.AspectRatioMode.KeepAspectRatio)


def render_page(ref: PageRef, target_w: int, zoom: float) -> QImage:
    """Decode and smooth-scale one page for display. Thread-safe."""
    img = decode_page(ref)
    if img.isNull():
        return img
    size = display_size(img.width(), img.height(), target_w, zoom)
    return img.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)


# ── Bounded cache (GUI thread) ───────────────────────────────────────────


def pixmap_bytes(pixmap: QPixmap) -> int:
    return pixmap.width() * pixmap.height() * max(1, pixmap.depth()) // 8


class PixmapCache:
    """LRU of scaled page pixmaps with a byte budget. GUI thread only.

    The newest entry is always kept, even when it alone exceeds the
    budget, so the page being read can never be evicted by itself."""

    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
        self._items: "OrderedDict[tuple, QPixmap]" = OrderedDict()
        self._bytes = 0

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key) -> bool:
        return key in self._items

    @property
    def total_bytes(self) -> int:
        return self._bytes

    def keys(self) -> List[tuple]:
        return list(self._items)

    def get(self, key) -> Optional[QPixmap]:
        pixmap = self._items.get(key)
        if pixmap is not None:
            self._items.move_to_end(key)
        return pixmap

    def put(self, key, pixmap: QPixmap):
        old = self._items.pop(key, None)
        if old is not None:
            self._bytes -= pixmap_bytes(old)
        self._items[key] = pixmap
        self._bytes += pixmap_bytes(pixmap)
        while self._bytes > self.max_bytes and len(self._items) > 1:
            _, evicted = self._items.popitem(last=False)
            self._bytes -= pixmap_bytes(evicted)

    def clear(self):
        self._items.clear()
        self._bytes = 0


# ── Worker pool ──────────────────────────────────────────────────────────


class PageLoader(QObject):
    """Decodes pages on worker threads and reports back on the GUI thread.

    Every chapter load calls reset(), which starts a new token: queued jobs
    are cancelled, running ones skip their work or have their result
    dropped by finish(). The pending map is GUI-thread state; workers only
    read the token."""

    # token, page index, target width, zoom, scaled image (null = failed)
    page_ready = Signal(int, int, int, float, QImage)

    def __init__(self, parent=None, max_workers: int = 2):
        super().__init__(parent)
        self._max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._token = 0
        self._closed = False
        self._pending: Dict[tuple, Future] = {}
        self._lock = threading.Lock()
        # Jobs inside _run per source file, so a caller can wait until no
        # worker still has a chapter file open (remove-after-read).
        self._idle = threading.Condition()
        self._running: Dict[Path, int] = {}

    @property
    def token(self) -> int:
        return self._token

    def has_pending(self) -> bool:
        return bool(self._pending)

    def is_pending(self, key: tuple) -> bool:
        return key in self._pending

    def reset(self) -> int:
        """Forget the current chapter's work and start a new token."""
        self._token += 1
        for future in self._pending.values():
            future.cancel()
        self._pending.clear()
        return self._token

    def request(self, index: int, ref: PageRef, target_w: int,
                zoom: float) -> bool:
        """Queue a page unless it is already pending. GUI thread only."""
        key = (index, target_w, zoom)
        if self._closed or key in self._pending:
            return False
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self._max_workers,
                    thread_name_prefix="memanga-reader")
            executor = self._executor
        try:
            future = executor.submit(self._run, self._token, index, ref,
                                     target_w, zoom)
        except RuntimeError:
            return False  # pool shut down (app closing)
        self._pending[key] = future
        return True

    def cancel_outside(self, wanted: Iterable[tuple]):
        """Cancel queued jobs whose key is not in *wanted*. Jobs already
        running finish; their result still lands in the cache."""
        wanted = set(wanted)
        for key in [k for k in self._pending if k not in wanted]:
            if self._pending[key].cancel():
                del self._pending[key]

    def finish(self, token: int, key: tuple) -> bool:
        """Record a delivered result. False when it is stale."""
        if token != self._token:
            return False
        self._pending.pop(key, None)
        return True

    def wait_idle(self, timeout: float,
                  path: Optional[Path] = None) -> bool:
        """Block until no job is running, or *timeout* seconds pass; with
        *path*, only jobs reading that file (or an image inside that
        folder) count. A timeout of 0 just checks. Call after reset():
        jobs starting later see the stale token and never open their
        file. True when idle."""
        with self._idle:
            return self._idle.wait_for(lambda: not self._busy_with(path),
                                       timeout)

    def _busy_with(self, path: Optional[Path]) -> bool:
        # Caller holds self._idle.
        if path is None:
            return bool(self._running)
        return any(source == path or path in source.parents
                   for source in self._running)

    def shutdown(self):
        self._closed = True
        self.reset()
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, token: int, index: int, ref: PageRef, target_w: int,
             zoom: float):
        # Counted before the token check, so a job that passes the check
        # is visible to wait_idle() for as long as it may touch the file.
        source = ref.source
        with self._idle:
            self._running[source] = self._running.get(source, 0) + 1
        try:
            self._render_and_emit(token, index, ref, target_w, zoom)
        finally:
            with self._idle:
                left = self._running[source] - 1
                if left:
                    self._running[source] = left
                else:
                    del self._running[source]
                self._idle.notify_all()

    def _render_and_emit(self, token: int, index: int, ref: PageRef,
                         target_w: int, zoom: float):
        if self._closed or token != self._token:
            return
        try:
            image = render_page(ref, target_w, zoom)
        except Exception as e:
            logger.warning("Couldn't render reader page %s (%s): %s",
                           ref.source, ref.member or ref.page, e)
            logger.debug("Reader page render traceback", exc_info=True)
            image = QImage()
        if self._closed or token != self._token:
            return
        try:
            self.page_ready.emit(token, index, target_w, zoom, image)
        except RuntimeError:
            pass  # loader deleted while the app was closing
