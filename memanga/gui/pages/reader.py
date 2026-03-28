"""
Reader page - Built-in vertical scroll manga reader with keyboard shortcuts and zoom.
"""

import io
import zipfile
from pathlib import Path
from typing import List, Optional

import customtkinter as ctk
from PIL import Image

from .base import BasePage
from ..theme import (
    PAD_SM, PAD_MD, PAD_LG, PAD_XL,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG, FONT_SIZE_XL, FONT_SIZE_XS,
    font, get_palette,
)


def _extract_images_from_file(filepath: Path) -> List[Image.Image]:
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
                    img = Image.open(io.BytesIO(data))
                    images.append(img)

    elif suffix == ".pdf":
        try:
            import fitz
            doc = fitz.open(str(filepath))
            for page in doc:
                pix = page.get_pixmap(dpi=150)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(img)
            doc.close()
        except ImportError:
            try:
                import pikepdf
                pdf = pikepdf.open(str(filepath))
                for page in pdf.pages:
                    for img_key in page.images:
                        raw = page.images[img_key]
                        pil_img = Image.open(io.BytesIO(raw.get_raw_stream_buffer()))
                        images.append(pil_img)
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
                        img = Image.open(io.BytesIO(data))
                        images.append(img)
        except Exception:
            pass

    return images


def _extract_images_from_folder(folder: Path) -> List[Image.Image]:
    extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    images = []
    files = sorted([f for f in folder.iterdir() if f.suffix.lower() in extensions])
    for f in files:
        try:
            images.append(Image.open(f))
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
        self._images: List[Image.Image] = []
        self._ctk_images: list = []
        self._content = None
        self._scroll = None
        self._zoom_level = 1.0
        self._fit_width = True
        self._page_labels: list = []
        self._page_indicator = None

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

        # Bind keyboard shortcuts (store binding ID for clean removal)
        self._key_bind_id = self.app.bind("<KeyPress>", self._on_key, add="+")

    def on_hide(self):
        self._images.clear()
        self._ctk_images.clear()
        self._page_labels.clear()
        if hasattr(self, "_key_bind_id") and self._key_bind_id:
            try:
                self.app.unbind("<KeyPress>", self._key_bind_id)
            except Exception:
                pass
            self._key_bind_id = None

    def _on_key(self, event):
        """Handle keyboard shortcuts."""
        key = event.keysym.lower()

        if key == "escape":
            if self._manga:
                self.app.show_page("detail", manga=self._manga)
            return

        if key in ("plus", "equal"):
            self._zoom_in()
        elif key == "minus":
            self._zoom_out()
        elif key == "f":
            self._toggle_fit_width()
        elif key == "n":
            self._go_next_chapter()
        elif key == "p":
            self._go_prev_chapter()

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
        """Re-render images at current zoom level."""
        if not self._scroll or not self._images:
            return

        # Clear existing image labels
        for lbl in self._page_labels:
            lbl.destroy()
        self._page_labels.clear()
        self._ctk_images.clear()

        self._render_images(self._scroll)

        # Update zoom indicator
        if self._page_indicator:
            self._page_indicator.configure(
                text=f"Zoom: {int(self._zoom_level * 100)}%  |  {len(self._images)} pages"
            )

    def _render_images(self, scroll):
        """Render all images into the scroll frame."""
        if self._fit_width:
            try:
                max_w = min(scroll.winfo_width() - 40, 1200)
            except Exception:
                max_w = self.DEFAULT_MAX_WIDTH
            if max_w < 300:
                max_w = self.DEFAULT_MAX_WIDTH
        else:
            max_w = self.DEFAULT_MAX_WIDTH

        max_w = int(max_w * self._zoom_level)

        for pil_img in self._images:
            w, h = pil_img.size
            if w > max_w:
                ratio = max_w / w
                w, h = int(w * ratio), int(h * ratio)
            else:
                w = int(w * self._zoom_level)
                h = int(h * self._zoom_level)

            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(w, h))
            self._ctk_images.append(ctk_img)

            lbl = ctk.CTkLabel(scroll, text="", image=ctk_img)
            lbl.pack(pady=1)
            self._page_labels.append(lbl)

    def _load_chapter(self):
        if self._content:
            self._content.destroy()

        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True)

        palette = get_palette(ctk.get_appearance_mode().lower())
        title = self._manga.get("title", "Unknown")

        # Top bar
        top = ctk.CTkFrame(self._content, fg_color=palette["bg_card"], height=44)
        top.pack(fill="x")
        top.pack_propagate(False)

        ctk.CTkButton(
            top, text="< Back", width=80, height=30,
            font=font(FONT_SIZE_SM), corner_radius=6,
            fg_color="transparent", hover_color=palette["bg_secondary"],
            text_color=palette["fg_secondary"],
            command=lambda: self.app.show_page("detail", manga=self._manga),
        ).pack(side="left", padx=PAD_SM, pady=6)

        ctk.CTkLabel(
            top, text=f"{title} - Chapter {self._chapter}",
            font=font(FONT_SIZE_MD, "bold"),
        ).pack(side="left", padx=PAD_SM)

        # Zoom controls
        zoom_frame = ctk.CTkFrame(top, fg_color="transparent")
        zoom_frame.pack(side="right", padx=PAD_SM)

        ctk.CTkButton(
            zoom_frame, text="-", width=28, height=26,
            font=font(FONT_SIZE_SM), corner_radius=4,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"], command=self._zoom_out,
        ).pack(side="left", padx=1)

        self._page_indicator = ctk.CTkLabel(
            zoom_frame, text=f"100%  |  ...",
            font=font(FONT_SIZE_XS), text_color=palette["fg_muted"], width=120,
        )
        self._page_indicator.pack(side="left", padx=PAD_SM)

        ctk.CTkButton(
            zoom_frame, text="+", width=28, height=26,
            font=font(FONT_SIZE_SM), corner_radius=4,
            fg_color=palette["bg_secondary"], hover_color=palette["border"],
            text_color=palette["fg"], command=self._zoom_in,
        ).pack(side="left", padx=1)

        # Chapter navigation
        downloaded = self.app.app_state.get_downloaded_chapters(title)
        try:
            idx = downloaded.index(str(self._chapter))
        except ValueError:
            idx = -1

        nav = ctk.CTkFrame(top, fg_color="transparent")
        nav.pack(side="right", padx=PAD_SM)

        if idx > 0:
            prev_ch = downloaded[idx - 1]
            ctk.CTkButton(
                nav, text="< Prev", width=70, height=26,
                font=font(FONT_SIZE_XS), corner_radius=4,
                fg_color=palette["bg_secondary"], hover_color=palette["border"],
                text_color=palette["fg"],
                command=lambda c=prev_ch: self._navigate_chapter(c),
            ).pack(side="left", padx=2)

        if idx >= 0 and idx < len(downloaded) - 1:
            next_ch = downloaded[idx + 1]
            ctk.CTkButton(
                nav, text="Next >", width=70, height=26,
                font=font(FONT_SIZE_XS), corner_radius=4,
                fg_color=palette["bg_secondary"], hover_color=palette["border"],
                text_color=palette["fg"],
                command=lambda c=next_ch: self._navigate_chapter(c),
            ).pack(side="left", padx=2)

        # Load images
        self._images = self._find_and_load_chapter()
        self._ctk_images.clear()
        self._page_labels.clear()

        if not self._images:
            download_dir = self.app.config.download_dir
            manga_dir = Path(download_dir) / self._manga.get("title", "")
            ctk.CTkLabel(
                self._content,
                text=f"Could not load chapter {self._chapter} images.\n\n"
                     f"Looked in: {manga_dir}\n"
                     f"The file may not have been downloaded yet.",
                font=font(FONT_SIZE_SM), text_color=palette["fg_muted"], justify="center",
            ).pack(expand=True, pady=80)
            return

        self._page_indicator.configure(
            text=f"{int(self._zoom_level * 100)}%  |  {len(self._images)} pages"
        )

        # Scrollable image area
        self._scroll = ctk.CTkScrollableFrame(self._content, fg_color=palette["bg"])
        self._scroll.pack(fill="both", expand=True)

        self._render_images(self._scroll)

        # Auto-advance: "Next Chapter" button at bottom
        if idx >= 0 and idx < len(downloaded) - 1:
            next_ch = downloaded[idx + 1]
            next_frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
            next_frame.pack(fill="x", pady=PAD_XL)

            ctk.CTkButton(
                next_frame, text=f"Next: Chapter {next_ch} >>", height=40, width=250,
                font=font(FONT_SIZE_MD, "bold"), corner_radius=8,
                fg_color=palette["accent"], hover_color=palette["accent_hover"],
                command=lambda c=next_ch: self._navigate_chapter(c),
            ).pack()

    def _find_and_load_chapter(self) -> List[Image.Image]:
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
