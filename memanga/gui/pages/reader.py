"""
Reader page - Built-in vertical scroll manga reader with keyboard shortcuts and zoom.
"""

import io
import zipfile
from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QWidget,
)
from PySide6.QtGui import QPixmap, QImage, QKeyEvent, QShortcut
from PySide6.QtCore import Qt, QByteArray, QBuffer

from .base import BasePage
from .. import theme as T


def _extract_images_from_file(filepath: Path) -> List[QImage]:
    """Extract images from a downloaded chapter file."""
    suffix = filepath.suffix.lower()
    images = []

    if suffix in (".cbz", ".zip"):
        with zipfile.ZipFile(filepath, "r") as zf:
            names = sorted([n for n in zf.namelist() if not n.startswith("__")])
            for name in names:
                ext = Path(name).suffix.lower()
                if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    data = zf.read(name)
                    img = QImage()
                    img.loadFromData(data)
                    if not img.isNull():
                        images.append(img)

    elif suffix == ".pdf":
        try:
            import fitz
            doc = fitz.open(str(filepath))
            for page in doc:
                pix = page.get_pixmap(dpi=150)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
                # Make a deep copy since pix.samples is transient
                images.append(img.copy())
            doc.close()
        except ImportError:
            try:
                from PIL import Image as PILImage
                import pikepdf
                pdf = pikepdf.open(str(filepath))
                for page in pdf.pages:
                    for img_key in page.images:
                        raw = page.images[img_key]
                        pil_img = PILImage.open(io.BytesIO(raw.get_raw_stream_buffer()))
                        buf = io.BytesIO()
                        pil_img.save(buf, format="PNG")
                        qimg = QImage()
                        qimg.loadFromData(buf.getvalue())
                        if not qimg.isNull():
                            images.append(qimg)
                pdf.close()
            except Exception:
                pass

    elif suffix == ".epub":
        try:
            with zipfile.ZipFile(filepath, "r") as zf:
                names = sorted(zf.namelist())
                for name in names:
                    ext = Path(name).suffix.lower()
                    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                        data = zf.read(name)
                        img = QImage()
                        img.loadFromData(data)
                        if not img.isNull():
                            images.append(img)
        except Exception:
            pass

    return images


def _extract_images_from_folder(folder: Path) -> List[QImage]:
    extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    images = []
    files = sorted([f for f in folder.iterdir() if f.suffix.lower() in extensions])
    for f in files:
        try:
            img = QImage(str(f))
            if not img.isNull():
                images.append(img)
        except Exception:
            pass
    return images


class ReaderPage(BasePage):
    """Vertical scroll manga reader with keyboard shortcuts and zoom."""

    ZOOM_MIN = 0.5
    ZOOM_MAX = 2.5
    ZOOM_STEP = 0.25
    DEFAULT_MAX_WIDTH = 800

    def __init__(self, parent, app):
        super().__init__(parent, app)
        self._manga = None
        self._chapter = None
        self._images: List[QImage] = []
        self._page_labels: list = []
        self._zoom_level = 1.0
        self._fit_width = True
        self._content: Optional[QWidget] = None
        self._scroll = None
        self._image_layout = None
        self._page_indicator = None

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def on_show(self, **kwargs):
        manga = kwargs.get("manga")
        chapter = kwargs.get("chapter")
        if manga:
            self._manga = manga
        if chapter:
            self._chapter = chapter
        self._zoom_level = 1.0
        self._fit_width = True
        if self._manga and self._chapter:
            self._load_chapter()
            # Save reading progress
            title = self._manga.get("title", "")
            if title:
                self.app.app_state.set_reading_progress(title, str(self._chapter))
        self.setFocus()

    def on_hide(self):
        self._images.clear()
        self._page_labels.clear()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            if self._manga:
                self.app.show_page("detail", manga=self._manga)
            return
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self._zoom_in()
        elif key == Qt.Key.Key_Minus:
            self._zoom_out()
        elif key == Qt.Key.Key_F:
            self._toggle_fit_width()
        elif key == Qt.Key.Key_N:
            self._go_next_chapter()
        elif key == Qt.Key.Key_P:
            self._go_prev_chapter()
        else:
            super().keyPressEvent(event)

    def _zoom_in(self):
        if self._zoom_level < self.ZOOM_MAX:
            self._zoom_level += self.ZOOM_STEP
            self._rebuild_images()

    def _zoom_out(self):
        if self._zoom_level > self.ZOOM_MIN:
            self._zoom_level -= self.ZOOM_STEP
            self._rebuild_images()

    def _toggle_fit_width(self):
        self._fit_width = not self._fit_width
        self._rebuild_images()

    def _rebuild_images(self):
        if not self._scroll or not self._images:
            return

        for lbl in self._page_labels:
            try:
                lbl.deleteLater()
            except Exception:
                pass
        self._page_labels.clear()

        self._render_images()

        if self._page_indicator:
            self._page_indicator.setText(
                f"Zoom: {int(self._zoom_level * 100)}%  |  {len(self._images)} pages"
            )

    def _render_images(self):
        if self._fit_width:
            try:
                max_w = min(self._scroll.width() - 40, 1200)
            except Exception:
                max_w = self.DEFAULT_MAX_WIDTH
            if max_w < 300:
                max_w = self.DEFAULT_MAX_WIDTH
        else:
            max_w = self.DEFAULT_MAX_WIDTH

        max_w = int(max_w * self._zoom_level)

        for qimg in self._images:
            w, h = qimg.width(), qimg.height()
            if w > max_w:
                ratio = max_w / w
                new_w, new_h = int(w * ratio), int(h * ratio)
            else:
                new_w = int(w * self._zoom_level)
                new_h = int(h * self._zoom_level)

            pm = QPixmap.fromImage(qimg).scaled(
                new_w, new_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            lbl = QLabel()
            lbl.setPixmap(pm)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._image_layout.addWidget(lbl)
            self._page_labels.append(lbl)

    def _load_chapter(self):
        # Tear down previous content
        if self._content:
            self._content.deleteLater()
            self._content = None

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Ensure this widget has a layout
        if not self.layout():
            QVBoxLayout(self)
            self.layout().setContentsMargins(0, 0, 0, 0)
            self.layout().setSpacing(0)
        self.layout().addWidget(self._content)

        title = self._manga.get("title", "Unknown")

        # ── Top bar ──
        top = QFrame()
        top.setFixedHeight(44)
        top.setStyleSheet(f"background-color: {T.BG_CARD};")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(T.PAD_SM, 0, T.PAD_SM, 0)
        top_layout.setSpacing(T.PAD_SM)

        back_btn = QPushButton("< Back")
        back_btn.setProperty("class", "flat")
        back_btn.setFixedHeight(30)
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(lambda: self.app.show_page("detail", manga=self._manga))
        top_layout.addWidget(back_btn)

        title_label = QLabel(f"{title} - Chapter {self._chapter}")
        title_label.setStyleSheet(f"font-size: {T.FONT_SIZE_MD}pt; font-weight: bold;")
        top_layout.addWidget(title_label)

        top_layout.addStretch()

        # Chapter navigation
        downloaded = self.app.app_state.get_downloaded_chapters(title)
        try:
            idx = downloaded.index(str(self._chapter))
        except ValueError:
            idx = -1

        if idx > 0:
            prev_ch = downloaded[idx - 1]
            prev_btn = QPushButton("< Prev")
            prev_btn.setFixedHeight(26)
            prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            prev_btn.clicked.connect(lambda checked=False, c=prev_ch: self._navigate_chapter(c))
            top_layout.addWidget(prev_btn)

        if idx >= 0 and idx < len(downloaded) - 1:
            next_ch = downloaded[idx + 1]
            next_btn = QPushButton("Next >")
            next_btn.setFixedHeight(26)
            next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            next_btn.clicked.connect(lambda checked=False, c=next_ch: self._navigate_chapter(c))
            top_layout.addWidget(next_btn)

        # Zoom controls
        zoom_minus = QPushButton("-")
        zoom_minus.setFixedSize(28, 26)
        zoom_minus.setCursor(Qt.CursorShape.PointingHandCursor)
        zoom_minus.clicked.connect(self._zoom_out)
        top_layout.addWidget(zoom_minus)

        self._page_indicator = QLabel(f"100%  |  ...")
        self._page_indicator.setStyleSheet(f"font-size: {T.FONT_SIZE_XS}pt; color: {T.FG_MUTED};")
        self._page_indicator.setFixedWidth(120)
        self._page_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_layout.addWidget(self._page_indicator)

        zoom_plus = QPushButton("+")
        zoom_plus.setFixedSize(28, 26)
        zoom_plus.setCursor(Qt.CursorShape.PointingHandCursor)
        zoom_plus.clicked.connect(self._zoom_in)
        top_layout.addWidget(zoom_plus)

        content_layout.addWidget(top)

        # ── Load images ──
        self._images = self._find_and_load_chapter()
        self._page_labels.clear()

        if not self._images:
            download_dir = self.app.config.download_dir
            manga_dir = Path(download_dir) / self._manga.get("title", "")
            empty = QLabel(
                f"Could not load chapter {self._chapter} images.\n\n"
                f"Looked in: {manga_dir}\n"
                f"The file may not have been downloaded yet."
            )
            empty.setStyleSheet(f"color: {T.FG_MUTED}; font-size: {T.FONT_SIZE_SM}pt;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            content_layout.addWidget(empty, 1)
            return

        self._page_indicator.setText(
            f"{int(self._zoom_level * 100)}%  |  {len(self._images)} pages"
        )

        # ── Scrollable image area ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"background-color: {T.BG};")

        scroll_content = QWidget()
        self._image_layout = QVBoxLayout(scroll_content)
        self._image_layout.setSpacing(1)
        self._image_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(scroll_content)

        self._render_images()

        # "Next Chapter" button at bottom
        if idx >= 0 and idx < len(downloaded) - 1:
            next_ch = downloaded[idx + 1]
            next_frame = QWidget()
            next_frame_layout = QHBoxLayout(next_frame)
            next_frame_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            next_chapter_btn = QPushButton(f"Next: Chapter {next_ch} >>")
            next_chapter_btn.setProperty("class", "accent")
            next_chapter_btn.setFixedHeight(40)
            next_chapter_btn.setFixedWidth(250)
            next_chapter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            next_chapter_btn.clicked.connect(
                lambda checked=False, c=next_ch: self._navigate_chapter(c)
            )
            next_frame_layout.addWidget(next_chapter_btn)
            self._image_layout.addSpacing(T.PAD_XL)
            self._image_layout.addWidget(next_frame)

        content_layout.addWidget(self._scroll, 1)

    def _find_and_load_chapter(self) -> List[QImage]:
        title = self._manga.get("title", "")
        ch = self._chapter
        download_dir = self.app.config.download_dir
        manga_dir = Path(download_dir) / title

        if not manga_dir.exists():
            return []

        def sanitize(name):
            for c in '<>:"/\\|?*':
                name = name.replace(c, '')
            return name.strip()[:100]

        patterns = [
            f"{sanitize(title)} - Chapter {ch}",
            f"{sanitize(title)} - Chapter {ch}.0",
        ]

        for pattern in patterns:
            for ext in [".pdf", ".epub", ".cbz", ".zip"]:
                filepath = manga_dir / f"{pattern}{ext}"
                if filepath.exists():
                    return _extract_images_from_file(filepath)

            folder = manga_dir / f"Chapter {ch}"
            if folder.is_dir():
                return _extract_images_from_folder(folder)

        # Fallback: scan directory
        ch_str = str(ch)
        for f in manga_dir.iterdir():
            if f.is_file() and f"chapter {ch_str}" in f.stem.lower():
                return _extract_images_from_file(f)
            if f.is_dir() and ch_str in f.name:
                return _extract_images_from_folder(f)

        return []

    def _navigate_chapter(self, chapter):
        self._chapter = chapter
        if self._manga:
            title = self._manga.get("title", "")
            if title:
                self.app.app_state.set_reading_progress(title, str(chapter))
        self._load_chapter()
        self.setFocus()

    def _go_next_chapter(self):
        if not self._manga:
            return
        title = self._manga.get("title", "")
        downloaded = self.app.app_state.get_downloaded_chapters(title)
        try:
            idx = downloaded.index(str(self._chapter))
            if idx < len(downloaded) - 1:
                self._navigate_chapter(downloaded[idx + 1])
        except ValueError:
            pass

    def _go_prev_chapter(self):
        if not self._manga:
            return
        title = self._manga.get("title", "")
        downloaded = self.app.app_state.get_downloaded_chapters(title)
        try:
            idx = downloaded.index(str(self._chapter))
            if idx > 0:
                self._navigate_chapter(downloaded[idx - 1])
        except ValueError:
            pass
