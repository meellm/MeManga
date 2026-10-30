"""
Lazy, off-UI-thread reader page loading (issues #389, #390).

Covers header-only chapter indexing for every format, the per-page decode
and scale, the bounded pixmap cache, the worker loader's thread handoff
and stale-result handling, and the reader's page window: no decode on the
main thread, memory bounded by the window instead of the chapter length,
paged-mode prefetch, resume position and failed pages.
"""

import io
import threading
import time
import zipfile
from pathlib import Path

import pytest


def _png(size=(40, 60), color="white") -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _jpg(size=(40, 60), color="white") -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def _stage_chapter(app_window, manga, make_cbz, *, pages, chapter="1"):
    """Drop a downloaded CBZ where the reader looks for it."""
    app_window.config.set("manga", [manga])
    title = manga["title"]
    dl = Path(app_window.config.download_dir) / title
    dl.mkdir(parents=True, exist_ok=True)
    cbz = make_cbz(pages=pages, name=f"ch{chapter}.cbz")
    (dl / f"{title} - Chapter {chapter}.cbz").write_bytes(cbz.read_bytes())
    app_window.app_state.add_downloaded_chapter(title, chapter)
    return title


def _settle(qtbot, reader):
    """Wait until every requested page has come back to the GUI thread."""
    qtbot.waitUntil(lambda: not reader._page_loader.has_pending(),
                    timeout=10000)


def _window_bound(reader):
    """Most pages the reader may hold decoded for its current position."""
    first, last, step = reader._visible_page_range()
    return ((last - first + 1)
            + (reader.PAGE_PREFETCH_AHEAD + reader.PAGE_PREFETCH_BEHIND)
            * step)


# ── Indexing ─────────────────────────────────────────────────────────────


class TestIndexing:
    def test_cbz_index_keeps_order_and_header_sizes(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import index_chapter_file
        cbz = tmp_path / "c.cbz"
        with zipfile.ZipFile(cbz, "w") as zf:
            zf.writestr("page001.jpg", _jpg((50, 70)))
            zf.writestr("page000.png", _png((40, 60)))
            zf.writestr("notes.txt", b"not a page")
            zf.writestr("__MACOSX/page000.png", _png())
            # A block page saved under an image name is not a page.
            zf.writestr("page002.jpg", b"<html>blocked</html>")
        pages = index_chapter_file(cbz)
        assert [p.member for p in pages] == ["page000.png", "page001.jpg"]
        assert [(p.width, p.height) for p in pages] == [(40, 60), (50, 70)]

    def test_epub_index_lists_every_image(self, qapp, tmp_path):
        # The duplicate EPUB cover is a separate issue; the reader still
        # shows what the archive holds.
        from memanga.gui.pages.reader_pages import index_chapter_file
        epub = tmp_path / "c.epub"
        with zipfile.ZipFile(epub, "w") as zf:
            zf.writestr("mimetype", b"application/epub+zip")
            zf.writestr("images/cover.jpg", _jpg())
            zf.writestr("images/page000.jpg", _jpg())
        pages = index_chapter_file(epub)
        assert [p.member for p in pages] == ["images/cover.jpg",
                                             "images/page000.jpg"]

    def test_folder_index(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import index_chapter_folder
        (tmp_path / "p001.png").write_bytes(_png((30, 90)))
        (tmp_path / "p000.jpg").write_bytes(_jpg((20, 40)))
        (tmp_path / "info.txt").write_text("x")
        pages = index_chapter_folder(tmp_path)
        assert [p.source.name for p in pages] == ["p000.jpg", "p001.png"]
        assert [(p.width, p.height) for p in pages] == [(20, 40), (30, 90)]

    def test_pdf_index_and_decode(self, qapp, tmp_path):
        import img2pdf
        from memanga.gui.pages.reader_pages import (KIND_PDF_PIKEPDF,
                                                    decode_page,
                                                    index_chapter_file)
        pdf = tmp_path / "c.pdf"
        pdf.write_bytes(img2pdf.convert([_jpg((40, 60)), _jpg((40, 60))]))
        pages = index_chapter_file(pdf)
        assert len(pages) == 2
        assert all(p.kind == KIND_PDF_PIKEPDF for p in pages)
        assert (pages[0].width, pages[0].height) == (40, 60)
        assert all(not decode_page(p).isNull() for p in pages)

    def test_unreadable_archive_indexes_empty(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import index_chapter_file
        bad = tmp_path / "c.cbz"
        bad.write_bytes(b"not a zip")
        assert index_chapter_file(bad) == []

    @staticmethod
    def _encoded(fmt, size) -> bytes:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", size, (90, 30, 150)).save(buf, fmt)
        return buf.getvalue()

    def _archive(self, tmp_path, pages):
        """A CBZ made by the real archive writer from (format, size,
        local file name) pages; local names deliberately disagree."""
        from memanga.downloader import _images_to_cbz
        paths = []
        for i, (fmt, size, local) in enumerate(pages):
            path = tmp_path / f"{i}-{local}"
            path.write_bytes(self._encoded(fmt, size))
            paths.append(path)
        cbz = tmp_path / "c.cbz"
        _images_to_cbz(paths, cbz)
        return cbz

    def test_writer_archive_with_renamed_pages_is_read_in_full(
            self, qapp, tmp_path):
        """BMP pages used to be archived as .jpg and Qt read them by
        content; named .bmp now, they must still be indexed and shown."""
        from memanga.gui.pages.reader_pages import (decode_page,
                                                    index_chapter_file)
        cbz = self._archive(tmp_path, [
            ("BMP", (30, 50), "p.jpg"),
            ("JPEG", (40, 60), "p.png"),
            ("PNG", (20, 70), "p.jpg"),
            ("GIF", (10, 30), "p"),
        ])
        pages = index_chapter_file(cbz)
        assert [p.member for p in pages] == [
            "page_000.bmp", "page_001.jpg", "page_002.png", "page_003.gif"]
        assert [(p.width, p.height) for p in pages] == [
            (30, 50), (40, 60), (20, 70), (10, 30)]
        for p in pages:
            img = decode_page(p)
            assert not img.isNull()
            assert (img.width(), img.height()) == (p.width, p.height)

    def test_writer_archive_tiff_page_is_read_when_qt_can(
            self, qapp, tmp_path):
        from PySide6.QtGui import QImageReader
        from memanga.gui.pages.reader_pages import (decode_page,
                                                    index_chapter_file)
        if b"tiff" not in [bytes(f) for f in
                           QImageReader.supportedImageFormats()]:
            pytest.skip("this Qt build has no TIFF image reader")
        cbz = self._archive(tmp_path, [("TIFF", (25, 35), "p.jpg")])
        (page,) = index_chapter_file(cbz)
        assert page.member == "page_000.tif"
        assert (page.width, page.height) == (25, 35)
        assert not decode_page(page).isNull()

    def test_writer_archive_ppm_page_is_read_when_qt_can(
            self, qapp, tmp_path):
        """PPM passes the page check (Pillow decodes it) and is archived
        as .ppm; the reader must index and decode it like any page."""
        from PySide6.QtGui import QImageReader
        from memanga.gui.pages.reader_pages import (decode_page,
                                                    index_chapter_file)
        if b"ppm" not in [bytes(f) for f in
                          QImageReader.supportedImageFormats()]:
            pytest.skip("this Qt build has no PPM image reader")
        cbz = self._archive(tmp_path, [("PPM", (26, 34), "p.jpg"),
                                       ("JPEG", (40, 60), "p.png")])
        pages = index_chapter_file(cbz)
        assert [p.member for p in pages] == ["page_000.ppm", "page_001.jpg"]
        assert (pages[0].width, pages[0].height) == (26, 34)
        img = decode_page(pages[0])
        assert not img.isNull()
        assert (img.width(), img.height()) == (26, 34)

    def test_every_extension_the_writer_names_is_indexed(self, qapp):
        from memanga.downloader.formats.cbz import (_PAGE_SIGNATURES,
                                                    archive_page_extensions)
        from memanga.gui.pages.reader_pages import (IMAGE_EXTENSIONS,
                                                    archive_member_extensions)
        assert {ext for ext, _ in _PAGE_SIGNATURES} <= set(IMAGE_EXTENSIONS)
        # Pillow-identified pages (.ppm, ...) are indexed in archives too.
        assert archive_page_extensions() <= archive_member_extensions()
        assert ".ppm" in archive_member_extensions()


# ── Decode / scale ───────────────────────────────────────────────────────


class TestRenderPage:
    def test_wide_page_shrinks_to_target_width(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import (display_size,
                                                    index_chapter_folder,
                                                    render_page)
        (tmp_path / "p.png").write_bytes(_png((1000, 3000)))
        ref = index_chapter_folder(tmp_path)[0]
        img = render_page(ref, 500, 1.0)
        assert (img.width(), img.height()) == (500, 1500)
        # Placeholders use the same size, so the layout never jumps.
        assert display_size(1000, 3000, 500, 1.0) == img.size()

    def test_narrow_page_follows_zoom(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import (display_size,
                                                    index_chapter_folder,
                                                    render_page)
        (tmp_path / "p.png").write_bytes(_png((400, 600)))
        ref = index_chapter_folder(tmp_path)[0]
        img = render_page(ref, 800, 1.5)
        assert (img.width(), img.height()) == (600, 900)
        assert display_size(400, 600, 800, 1.5) == img.size()

    def test_missing_source_decodes_null(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import (KIND_ZIP, PageRef,
                                                    decode_page)
        ref = PageRef(tmp_path / "gone.cbz", KIND_ZIP, member="p.jpg",
                      width=10, height=10)
        assert decode_page(ref).isNull()


# ── PDF pages via pikepdf (issues #390, #382) ────────────────────────────


def _image_pdf(path, images):
    """Write a PDF with one image XObject per page, drawn over the whole
    page the way img2pdf does. Each image is (stream data, /Filter name
    or None, colour space name or array, (width, height))."""
    import pikepdf
    with pikepdf.new() as pdf:
        for data, filter_, colorspace, (width, height) in images:
            image = pikepdf.Stream(pdf, b"")
            image.write(data, filter=(pikepdf.Name(filter_)
                                      if filter_ else None))
            image.Type = pikepdf.Name.XObject
            image.Subtype = pikepdf.Name.Image
            image.Width = width
            image.Height = height
            image.ColorSpace = (pikepdf.Name(colorspace)
                                if isinstance(colorspace, str)
                                else colorspace)
            image.BitsPerComponent = 8
            page = pdf.add_blank_page(page_size=(width, height))
            page.obj.Resources = pikepdf.Dictionary(
                XObject=pikepdf.Dictionary(Im0=image))
            page.obj.Contents = pdf.make_stream(
                b"q %d 0 0 %d 0 0 cm /Im0 Do Q" % (width, height))
        pdf.save(path)
    return path


def _edit_pdf(path, edit):
    """Change a saved PDF in place: edit(pdf) gets the open document."""
    import pikepdf
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        edit(pdf)
        pdf.save(path)
    return path


def _blue_square_form(pdf):
    """A 30x30 pt form XObject that paints itself blue."""
    import pikepdf
    form = pdf.make_stream(b"0 0 1 rg 0 0 30 30 re f")
    form.Type = pikepdf.Name.XObject
    form.Subtype = pikepdf.Name.Form
    form.BBox = pikepdf.Array([0, 0, 30, 30])
    return form


def _rendered(pt):
    """Pixels of *pt* points at the reader's PDF render resolution."""
    return round(pt * 150 / 72)


class TestPdfFallback:
    @pytest.fixture(autouse=True)
    def _pikepdf(self):
        pytest.importorskip("pikepdf")

    @pytest.fixture
    def pil_saves(self, monkeypatch):
        from PIL import Image
        saves = []
        real_save = Image.Image.save

        def spy(img, fp, format=None, **params):
            saves.append(format)
            return real_save(img, fp, format, **params)
        monkeypatch.setattr(Image.Image, "save", spy)
        return saves

    @staticmethod
    def _pages(pdf):
        from memanga.gui.pages.reader_pages import (KIND_PDF_PIKEPDF,
                                                    index_chapter_file)
        pages = index_chapter_file(pdf)
        assert pages and all(p.kind == KIND_PDF_PIKEPDF for p in pages)
        return pages

    def test_jpeg_page_loads_straight_into_qimage(
            self, qapp, tmp_path, monkeypatch, pil_saves):
        import pikepdf
        from memanga.gui.pages.reader_pages import decode_page
        jpg = _jpg((80, 120), "red")
        pdf = _image_pdf(tmp_path / "c.pdf",
                         [(jpg, "/DCTDecode", "/DeviceRGB", (80, 120))])
        ref = self._pages(pdf)[0]
        pil_saves.clear()

        def no_pillow(self):
            raise AssertionError("JPEG page went through Pillow")
        monkeypatch.setattr(pikepdf.PdfImage, "as_pil_image", no_pillow)
        img = decode_page(ref)
        assert (img.width(), img.height()) == (80, 120)
        assert pil_saves == []

    def test_jpeg_in_calibrated_colour_space_still_loads(
            self, qapp, tmp_path, pil_saves):
        # pikepdf has no Pillow mode for /CalRGB; the stream is still a
        # plain JPEG that Qt reads as stored.
        import pikepdf
        from memanga.gui.pages.reader_pages import decode_page
        cal_rgb = pikepdf.Array([pikepdf.Name.CalRGB, pikepdf.Dictionary(
            WhitePoint=pikepdf.Array([0.9505, 1.0, 1.089]))])
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (_jpg((80, 120), "red"), "/DCTDecode", cal_rgb, (80, 120)),
        ])
        ref = self._pages(pdf)[0]
        pil_saves.clear()
        img = decode_page(ref)
        assert (img.width(), img.height()) == (80, 120)
        color = img.pixelColor(40, 60)
        assert color.red() > 200 and color.green() < 60
        assert pil_saves == []

    @pytest.mark.parametrize("colorspace, pixel, expected", [
        ("/DeviceRGB", bytes((200, 30, 60)), (200, 30, 60)),
        ("/DeviceGray", bytes((128,)), (128, 128, 128)),
    ])
    def test_flate_page_decodes_without_reencoding(
            self, qapp, tmp_path, pil_saves, colorspace, pixel, expected):
        import zlib
        from memanga.gui.pages.reader_pages import decode_page
        width, height = 40, 60
        data = zlib.compress(pixel * (width * height))
        pdf = _image_pdf(tmp_path / "c.pdf",
                         [(data, "/FlateDecode", colorspace, (width, height))])
        ref = self._pages(pdf)[0]
        assert (ref.width, ref.height) == (width, height)
        img = decode_page(ref)
        assert (img.width(), img.height()) == (width, height)
        color = img.pixelColor(width // 2, height // 2)
        assert (color.red(), color.green(), color.blue()) == expected
        assert pil_saves == []

    def test_pages_keep_their_order(self, qapp, tmp_path):
        import zlib
        from memanga.gui.pages.reader_pages import decode_page
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (_jpg((30, 50)), "/DCTDecode", "/DeviceRGB", (30, 50)),
            (zlib.compress(b"\x00" * (20 * 70)), "/FlateDecode",
             "/DeviceGray", (20, 70)),
        ])
        pages = self._pages(pdf)
        assert [decode_page(p).size().toTuple() for p in pages] == \
            [(30, 50), (20, 70)]

    def test_broken_page_decodes_null_and_logs_a_warning(
            self, qapp, tmp_path, caplog):
        import logging
        from memanga.gui.pages.reader_pages import decode_page
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (b"\xff\xd8 not a jpeg", "/DCTDecode", "/DeviceRGB", (80, 120)),
        ])
        ref = self._pages(pdf)[0]
        with caplog.at_level(logging.WARNING,
                             logger="memanga.gui.pages.reader_pages"):
            assert decode_page(ref).isNull()
        warnings = [r for r in caplog.records
                    if r.name == "memanga.gui.pages.reader_pages"
                    and r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "c.pdf" in warnings[0].getMessage()

    def test_installed_pymupdf_is_never_used(
            self, qapp, tmp_path, monkeypatch):
        # PyMuPDF is AGPL and undeclared (issue #382): having it installed
        # must not change how the reader reads a PDF.
        import sys
        import types
        from memanga.gui.pages.reader_pages import decode_page
        touched = []

        def stub(name):
            mod = types.ModuleType(name)

            def getattr_(attr):
                if attr.startswith("__"):
                    raise AttributeError(attr)
                touched.append((name, attr))
                raise AttributeError(attr)
            mod.__getattr__ = getattr_
            return mod
        for name in ("fitz", "pymupdf"):
            monkeypatch.setitem(sys.modules, name, stub(name))
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (_jpg((80, 120), "red"), "/DCTDecode", "/DeviceRGB", (80, 120)),
        ])
        pages = self._pages(pdf)
        assert [(p.width, p.height) for p in pages] == [(80, 120)]
        assert decode_page(pages[0]).size().toTuple() == (80, 120)
        assert touched == []

    def test_reader_pages_do_not_import_pymupdf(self):
        import subprocess
        import sys
        code = (
            "import sys, memanga.gui.pages.reader_pages; "
            "sys.exit(1 if any(m.split('.')[0] in ('fitz', 'pymupdf') "
            "for m in sys.modules) else 0)"
        )
        assert subprocess.run([sys.executable, "-c", code],
                              timeout=60).returncode == 0

    def test_own_pdf_pages_are_shown_as_stored(self, qapp, tmp_path):
        # A MeManga (img2pdf) page is exactly one image: pikepdf, native
        # size, Qt PDF not even loaded.
        import subprocess
        import sys
        import img2pdf
        pdf = tmp_path / "c.pdf"
        pdf.write_bytes(img2pdf.convert([_jpg((40, 60)), _png((30, 90))]))
        assert [(p.width, p.height) for p in self._pages(pdf)] == \
            [(40, 60), (30, 90)]
        code = (
            "import sys; from pathlib import Path; "
            "from memanga.gui.pages.reader_pages import index_chapter_file; "
            "index_chapter_file(Path(sys.argv[1])); "
            "sys.exit(1 if 'PySide6.QtPdf' in sys.modules else 0)"
        )
        assert subprocess.run([sys.executable, "-c", code, str(pdf)],
                              timeout=60).returncode == 0

    @staticmethod
    def _add_text(pdf, page):
        import pikepdf
        page.obj.Resources.Font = pikepdf.Dictionary(F1=pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name.Helvetica))
        page.contents_add(pdf.make_stream(
            b"BT 0 g /F1 40 Tf 5 10 Td (HI) Tj ET"))

    @staticmethod
    def _add_vector(pdf, page):
        page.contents_add(pdf.make_stream(b"0 0 1 rg 10 10 30 30 re f"))

    @staticmethod
    def _add_link(pdf, page):
        # A link whose appearance stream paints a visible blue box.
        import pikepdf
        page.obj.Annots = pdf.make_indirect(pikepdf.Array([
            pikepdf.Dictionary(
                Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
                Rect=pikepdf.Array([10, 10, 40, 40]),
                Border=pikepdf.Array([0, 0, 0]),
                AP=pikepdf.Dictionary(N=_blue_square_form(pdf)))]))

    @staticmethod
    def _add_form_xobject(pdf, page):
        page.obj.Resources.XObject.Fx0 = _blue_square_form(pdf)
        page.contents_add(pdf.make_stream(b"q 1 0 0 1 10 10 cm /Fx0 Do Q"))

    @pytest.mark.parametrize("extra", [
        "_add_text", "_add_vector", "_add_link", "_add_form_xobject",
    ], ids=["text", "vector", "visible-link", "form-xobject"])
    def test_page_with_more_than_its_image_is_rendered_whole(
            self, qapp, tmp_path, extra):
        # Showing only the image would drop the rest of the page
        # (issue #382): such a page is rendered whole, at 150 dpi.
        from memanga.gui.pages.reader_pages import (KIND_PDF_PIKEPDF,
                                                    KIND_PDF_RENDER,
                                                    decode_page,
                                                    index_chapter_file)
        jpg = _jpg((80, 120), "red")
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (jpg, "/DCTDecode", "/DeviceRGB", (80, 120)),
            (jpg, "/DCTDecode", "/DeviceRGB", (80, 120)),
        ])
        # The second page gets the extra content.
        _edit_pdf(pdf, lambda doc: getattr(self, extra)(doc, doc.pages[1]))
        pages = index_chapter_file(pdf)
        assert [(p.kind, p.page) for p in pages] == [
            (KIND_PDF_PIKEPDF, 0), (KIND_PDF_RENDER, 1)]
        size = (_rendered(80), _rendered(120))
        assert (pages[1].width, pages[1].height) == size
        img = decode_page(pages[1])
        assert img.size().toTuple() == size
        # Top of the page: the image, red.
        top = img.pixelColor(_rendered(40), _rendered(20))
        assert top.red() > 200 and top.blue() < 60
        # Bottom left: the extra content, not the image's red.
        bottom = [img.pixelColor(x, y)
                  for x in range(_rendered(10), _rendered(40))
                  for y in range(_rendered(80), _rendered(110))]
        if extra == "_add_text":
            assert any(c.red() < 100 for c in bottom)
        else:
            centre = img.pixelColor(_rendered(25), _rendered(120 - 25))
            assert centre.blue() > 200 and centre.red() < 60

    @pytest.mark.parametrize("change, size", [
        ("rotate", (120, 80)),
        ("crop", (40, 60)),
    ])
    def test_rotated_or_cropped_page_is_rendered_as_shown(
            self, qapp, tmp_path, change, size):
        import pikepdf
        from memanga.gui.pages.reader_pages import (KIND_PDF_RENDER,
                                                    decode_page,
                                                    index_chapter_file)
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (_jpg((80, 120), "red"), "/DCTDecode", "/DeviceRGB", (80, 120)),
        ])

        def edit(doc):
            if change == "rotate":
                doc.pages[0].obj.Rotate = 90
            else:
                doc.pages[0].obj.CropBox = pikepdf.Array([0, 0, 40, 60])
        _edit_pdf(pdf, edit)
        (ref,) = index_chapter_file(pdf)
        expected = (_rendered(size[0]), _rendered(size[1]))
        assert ref.kind == KIND_PDF_RENDER
        assert (ref.width, ref.height) == expected
        assert decode_page(ref).size().toTuple() == expected

    def test_page_without_image_is_rendered_on_white(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import (KIND_PDF_PIKEPDF,
                                                    KIND_PDF_RENDER,
                                                    decode_page,
                                                    index_chapter_file)
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (_jpg((80, 120)), "/DCTDecode", "/DeviceRGB", (80, 120)),
        ])
        _edit_pdf(pdf, lambda doc: doc.add_blank_page(page_size=(72, 144)))
        pages = index_chapter_file(pdf)
        assert [p.kind for p in pages] == [KIND_PDF_PIKEPDF, KIND_PDF_RENDER]
        img = decode_page(pages[1])
        assert img.size().toTuple() == (150, 300)
        corner = img.pixelColor(5, 5)
        assert (corner.red(), corner.green(), corner.blue(),
                corner.alpha()) == (255, 255, 255, 255)

    @staticmethod
    def _add_text_field(pdf, page, *, appearance, need_appearances=None,
                        value="HI", flags=4):
        """A text field over the image's bottom left, filled with *value*.
        With *appearance* it carries its own blue appearance stream;
        without, by default the form asks the viewer to draw the value
        (NeedAppearances)."""
        import pikepdf
        field = pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
            FT=pikepdf.Name.Tx, T=pikepdf.String("name"),
            F=flags, DA=pikepdf.String("/Helv 30 Tf 0 g"),
            Rect=pikepdf.Array([10, 10, 40, 40]),
            P=page.obj)
        if value is not None:
            field.V = pikepdf.String(value)
        if appearance:
            field.AP = pikepdf.Dictionary(N=_blue_square_form(pdf))
        if need_appearances is None:
            need_appearances = not appearance
        field = pdf.make_indirect(field)
        page.obj.Annots = pdf.make_indirect(pikepdf.Array([field]))
        pdf.Root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(
            Fields=pikepdf.Array([field]),
            NeedAppearances=need_appearances,
            DA=pikepdf.String("/Helv 30 Tf 0 g"),
            DR=pikepdf.Dictionary(Font=pikepdf.Dictionary(
                Helv=pikepdf.Dictionary(
                    Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                    BaseFont=pikepdf.Name.Helvetica)))))

    @pytest.mark.parametrize("appearance", [True, False],
                             ids=["own-appearance", "need-appearances"])
    def test_filled_form_field_is_drawn(self, qapp, tmp_path, appearance):
        # Qt PDF draws no form fields: the page's fields are burned into a
        # one-page copy in memory first (issue #382). The file is only read.
        from memanga.gui.pages.reader_pages import (KIND_PDF_FORM,
                                                    decode_page,
                                                    index_chapter_file)
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (_jpg((80, 120), "red"), "/DCTDecode", "/DeviceRGB", (80, 120)),
            (_jpg((80, 120), "red"), "/DCTDecode", "/DeviceRGB", (80, 120)),
        ])
        _edit_pdf(pdf, lambda doc: self._add_text_field(
            doc, doc.pages[1], appearance=appearance))
        before = pdf.read_bytes()
        pages = index_chapter_file(pdf)
        assert pages[1].kind == KIND_PDF_FORM
        size = (_rendered(80), _rendered(120))
        assert (pages[1].width, pages[1].height) == size
        img = decode_page(pages[1])
        assert img.size().toTuple() == size
        top = img.pixelColor(_rendered(40), _rendered(20))
        assert top.red() > 200 and top.blue() < 60
        field = [img.pixelColor(x, y)
                 for x in range(_rendered(10), _rendered(40))
                 for y in range(_rendered(80), _rendered(110))]
        if appearance:
            centre = img.pixelColor(_rendered(25), _rendered(120 - 25))
            assert centre.blue() > 200 and centre.red() < 60
        else:
            # qpdf drew the value "HI" in black from the field's /DA.
            assert any(c.red() < 100 for c in field)
        assert pdf.read_bytes() == before

    def test_filled_field_without_appearance_fails_visibly(
            self, qapp, tmp_path, caplog):
        # No /AP and no NeedAppearances: nothing can draw the value, so the
        # page is a failed page, not the page without its field.
        import logging
        from memanga.gui.pages.reader_pages import (KIND_PDF_FORM,
                                                    decode_page,
                                                    index_chapter_file)
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (_jpg((80, 120)), "/DCTDecode", "/DeviceRGB", (80, 120)),
        ])
        _edit_pdf(pdf, lambda doc: self._add_text_field(
            doc, doc.pages[0], appearance=False, need_appearances=False))
        (ref,) = index_chapter_file(pdf)
        assert ref.kind == KIND_PDF_FORM
        with caplog.at_level(logging.WARNING,
                             logger="memanga.gui.pages.reader_pages"):
            assert decode_page(ref).isNull()
        warnings = [r.getMessage() for r in caplog.records
                    if r.name == "memanga.gui.pages.reader_pages"
                    and r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "no appearance to draw" in warnings[0]

    @pytest.mark.parametrize("value, flags", [
        (None, 4),   # empty field: nothing to lose
        ("", 4),
        ("HI", 4 | 2),   # hidden
        ("HI", 4 | 32),  # not shown on screen (NoView)
    ], ids=["no-value", "empty-value", "hidden", "no-view"])
    def test_field_with_nothing_to_show_does_not_fail_the_page(
            self, qapp, tmp_path, value, flags):
        from memanga.gui.pages.reader_pages import (decode_page,
                                                    index_chapter_file)
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (_jpg((80, 120), "red"), "/DCTDecode", "/DeviceRGB", (80, 120)),
        ])
        _edit_pdf(pdf, lambda doc: self._add_text_field(
            doc, doc.pages[0], appearance=False, need_appearances=False,
            value=value, flags=flags))
        (ref,) = index_chapter_file(pdf)
        img = decode_page(ref)
        assert img.size().toTuple() == (_rendered(80), _rendered(120))
        top = img.pixelColor(_rendered(40), _rendered(20))
        assert top.red() > 200 and top.blue() < 60

    @staticmethod
    def _add_checkbox_from_parent(pdf, page, *, value, appearance):
        """A checkbox widget with no /AS whose parent field holds the
        value; with *appearance* the widget has a blue /Yes state."""
        import pikepdf
        parent = pdf.make_indirect(pikepdf.Dictionary(
            FT=pikepdf.Name.Btn, T=pikepdf.String("box"),
            V=pikepdf.Name(value)))
        widget = pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, F=4,
            Parent=parent, Rect=pikepdf.Array([10, 10, 40, 40]),
            P=page.obj)
        if appearance:
            widget.AP = pikepdf.Dictionary(N=pikepdf.Dictionary(
                Yes=_blue_square_form(pdf)))
        widget = pdf.make_indirect(widget)
        parent.Kids = pikepdf.Array([widget])
        page.obj.Annots = pdf.make_indirect(pikepdf.Array([widget]))
        pdf.Root.AcroForm = pdf.make_indirect(pikepdf.Dictionary(
            Fields=pikepdf.Array([parent])))

    def test_checkbox_checked_by_parent_value_without_appearance_fails(
            self, qapp, tmp_path, caplog):
        # /V /Yes on the parent, no /AS and no /AP on the widget: the
        # checked state can't be drawn, so the page fails visibly.
        import logging
        from memanga.gui.pages.reader_pages import (KIND_PDF_FORM,
                                                    decode_page,
                                                    index_chapter_file)
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (_jpg((80, 120)), "/DCTDecode", "/DeviceRGB", (80, 120)),
        ])
        _edit_pdf(pdf, lambda doc: self._add_checkbox_from_parent(
            doc, doc.pages[0], value="/Yes", appearance=False))
        (ref,) = index_chapter_file(pdf)
        assert ref.kind == KIND_PDF_FORM
        with caplog.at_level(logging.WARNING,
                             logger="memanga.gui.pages.reader_pages"):
            assert decode_page(ref).isNull()
        warnings = [r.getMessage() for r in caplog.records
                    if r.name == "memanga.gui.pages.reader_pages"
                    and r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "1 filled-in form field(s)" in warnings[0]

    def test_checkbox_checked_by_parent_value_draws_its_state(
            self, qapp, tmp_path):
        # No /AS, but the parent's /V names a state the widget can draw.
        from memanga.gui.pages.reader_pages import (decode_page,
                                                    index_chapter_file)
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (_jpg((80, 120), "red"), "/DCTDecode", "/DeviceRGB", (80, 120)),
        ])
        _edit_pdf(pdf, lambda doc: self._add_checkbox_from_parent(
            doc, doc.pages[0], value="/Yes", appearance=True))
        before = pdf.read_bytes()
        (ref,) = index_chapter_file(pdf)
        img = decode_page(ref)
        centre = img.pixelColor(_rendered(25), _rendered(120 - 25))
        assert centre.blue() > 200 and centre.red() < 60
        assert pdf.read_bytes() == before

    @pytest.mark.parametrize("appearance", [False, True],
                             ids=["no-appearance", "with-appearance"])
    def test_unchecked_parent_value_does_not_fail_the_page(
            self, qapp, tmp_path, appearance):
        from memanga.gui.pages.reader_pages import (decode_page,
                                                    index_chapter_file)
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (_jpg((80, 120), "red"), "/DCTDecode", "/DeviceRGB", (80, 120)),
        ])
        _edit_pdf(pdf, lambda doc: self._add_checkbox_from_parent(
            doc, doc.pages[0], value="/Off", appearance=appearance))
        (ref,) = index_chapter_file(pdf)
        img = decode_page(ref)
        assert img.size().toTuple() == (_rendered(80), _rendered(120))
        # Nothing drawn over the image where the box would be.
        centre = img.pixelColor(_rendered(25), _rendered(120 - 25))
        assert centre.red() > 200 and centre.blue() < 60

    @pytest.mark.parametrize("state, drawn", [
        ("/Yes", True), ("/Maybe", False),
    ], ids=["state-with-appearance", "state-without-appearance"])
    def test_checked_box_needs_an_appearance_for_its_state(
            self, qapp, tmp_path, state, drawn):
        # A checkbox's appearance is a dictionary of states; the one /AS
        # names must exist, as qpdf never generates button appearances.
        import pikepdf
        from memanga.gui.pages.reader_pages import (decode_page,
                                                    index_chapter_file)
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (_jpg((80, 120), "red"), "/DCTDecode", "/DeviceRGB", (80, 120)),
        ])

        def add_box(doc):
            page = doc.pages[0]
            box = doc.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
                FT=pikepdf.Name.Btn, T=pikepdf.String("box"), F=4,
                V=pikepdf.Name(state), AS=pikepdf.Name(state),
                Rect=pikepdf.Array([10, 10, 40, 40]), P=page.obj,
                AP=pikepdf.Dictionary(N=pikepdf.Dictionary(
                    Yes=_blue_square_form(doc)))))
            page.obj.Annots = doc.make_indirect(pikepdf.Array([box]))
            doc.Root.AcroForm = doc.make_indirect(pikepdf.Dictionary(
                Fields=pikepdf.Array([box])))
        _edit_pdf(pdf, add_box)
        (ref,) = index_chapter_file(pdf)
        img = decode_page(ref)
        if drawn:
            centre = img.pixelColor(_rendered(25), _rendered(120 - 25))
            assert centre.blue() > 200 and centre.red() < 60
        else:
            assert img.isNull()

    def test_broken_form_page_fails_visibly(self, qapp, tmp_path,
                                            monkeypatch):
        # A form page that can't be flattened is a failed page, never the
        # page without its fields.
        from memanga.gui.pages import reader_pages
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (_jpg((80, 120)), "/DCTDecode", "/DeviceRGB", (80, 120)),
        ])
        _edit_pdf(pdf, lambda doc: self._add_text_field(
            doc, doc.pages[0], appearance=True))
        (ref,) = reader_pages.index_chapter_file(pdf)

        def broken(ref):
            raise RuntimeError("flatten failed")
        monkeypatch.setattr(reader_pages, "_flattened_form_page", broken)
        assert reader_pages.decode_page(ref).isNull()

    def test_rendered_pages_decode_concurrently(self, qapp, tmp_path):
        # The reader decodes on a worker pool; Qt PDF serializes PDFium.
        from concurrent.futures import ThreadPoolExecutor
        from memanga.gui.pages.reader_pages import (KIND_PDF_RENDER,
                                                    decode_page,
                                                    index_chapter_file)
        pdf = _image_pdf(tmp_path / "c.pdf", [
            (_jpg((80, 120), "red"), "/DCTDecode", "/DeviceRGB", (80, 120)),
        ] * 6)

        def rotate(doc):
            for page in doc.pages:
                page.obj.Rotate = 180
        _edit_pdf(pdf, rotate)
        pages = index_chapter_file(pdf)
        assert all(p.kind == KIND_PDF_RENDER for p in pages)
        with ThreadPoolExecutor(max_workers=4) as pool:
            images = list(pool.map(decode_page, pages * 3))
        assert all(img.size().toTuple() == (_rendered(80), _rendered(120))
                   for img in images)


# ── Cache ────────────────────────────────────────────────────────────────


class TestPixmapCache:
    def test_byte_budget_evicts_least_recent(self, qapp):
        from PySide6.QtGui import QPixmap
        from memanga.gui.pages.reader_pages import PixmapCache, pixmap_bytes
        one = pixmap_bytes(QPixmap(100, 100))
        cache = PixmapCache(max_bytes=one * 2)
        for key in ("a", "b"):
            cache.put(key, QPixmap(100, 100))
        cache.get("a")  # a is now the most recent
        cache.put("c", QPixmap(100, 100))
        assert cache.keys() == ["a", "c"]
        assert cache.total_bytes <= cache.max_bytes

    def test_oversized_newest_entry_is_kept(self, qapp):
        from PySide6.QtGui import QPixmap
        from memanga.gui.pages.reader_pages import PixmapCache
        cache = PixmapCache(max_bytes=1)
        cache.put("a", QPixmap(10, 10))
        cache.put("b", QPixmap(10, 10))
        assert cache.keys() == ["b"]


# ── Loader thread handoff ────────────────────────────────────────────────


class TestPageLoader:
    def _ref(self, tmp_path):
        from memanga.gui.pages.reader_pages import index_chapter_folder
        (tmp_path / "p.png").write_bytes(_png((40, 60)))
        return index_chapter_folder(tmp_path)[0]

    def test_decodes_off_thread_and_delivers_on_gui_thread(
            self, qapp, qtbot, tmp_path, monkeypatch):
        from PySide6.QtCore import QObject, Qt
        from memanga.gui.pages import reader_pages
        decode_threads = []
        real_decode = reader_pages.decode_page

        def spy(ref):
            decode_threads.append(threading.current_thread())
            return real_decode(ref)
        monkeypatch.setattr(reader_pages, "decode_page", spy)

        class Receiver(QObject):
            """GUI-thread QObject, like the reader page."""
            def __init__(self):
                super().__init__()
                self.got = []

            def on_ready(self, *args):
                self.got.append((threading.current_thread(), args))

        loader = reader_pages.PageLoader()
        receiver = Receiver()
        loader.page_ready.connect(receiver.on_ready,
                                  Qt.ConnectionType.QueuedConnection)
        try:
            token = loader.token
            assert loader.request(0, self._ref(tmp_path), 800, 1.0)
            qtbot.waitUntil(lambda: bool(receiver.got), timeout=10000)
        finally:
            loader.shutdown()
        delivered = receiver.got
        assert decode_threads
        assert all(t is not threading.main_thread() for t in decode_threads)
        assert decode_threads[0].name.startswith("memanga-reader")
        thread, (got_token, index, _w, _zoom, image) = delivered[0]
        assert thread is threading.main_thread()
        assert (got_token, index) == (token, 0)
        assert not image.isNull()

    def test_reset_makes_results_stale(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import PageLoader
        loader = PageLoader()
        try:
            old = loader.token
            loader.request(0, self._ref(tmp_path), 800, 1.0)
            loader.reset()
            assert not loader.has_pending()
            assert loader.finish(old, (0, 800, 1.0)) is False
        finally:
            loader.shutdown()

    def test_shutdown_refuses_new_work(self, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import PageLoader
        loader = PageLoader()
        loader.shutdown()
        assert loader.request(0, self._ref(tmp_path), 800, 1.0) is False

    def test_wait_idle_matches_a_folder_chapter_by_its_images(
            self, qapp, tmp_path, monkeypatch):
        from memanga.gui.pages import reader_pages
        folder = tmp_path / "Chapter 1"
        other = tmp_path / "Chapter 2"
        folder.mkdir()
        other.mkdir()
        ref = self._ref(folder)
        gate = threading.Event()
        started = threading.Event()

        def held_decode(ref):
            started.set()
            gate.wait(10)
            return reader_pages.QImage()
        monkeypatch.setattr(reader_pages, "decode_page", held_decode)
        loader = reader_pages.PageLoader()
        try:
            loader.request(0, ref, 800, 1.0)
            assert started.wait(5)
            # The job reads folder/p.png: the folder is busy, others not.
            assert loader.wait_idle(0, folder) is False
            assert loader.wait_idle(0, ref.source) is False
            assert loader.wait_idle(0, other) is True
            gate.set()
            assert loader.wait_idle(5, folder) is True
        finally:
            gate.set()
            loader.shutdown()


# ── Reader page window ───────────────────────────────────────────────────


@pytest.fixture
def decode_spy(monkeypatch):
    """Record which thread decodes which page."""
    from memanga.gui.pages import reader_pages
    calls = []
    real_decode = reader_pages.decode_page

    def spy(ref):
        calls.append((ref.member, threading.current_thread()))
        return real_decode(ref)
    monkeypatch.setattr(reader_pages, "decode_page", spy)
    return calls


class TestReaderLazyLoading:
    def test_open_decodes_only_the_window_and_never_on_main_thread(
            self, app_window, qapp, qtbot, sample_manga, make_cbz,
            decode_spy):
        _stage_chapter(app_window, sample_manga, make_cbz, pages=30)
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        # Every page is known (and laid out) up front...
        assert len(reader._images) == 30
        assert len(reader._page_labels) == 30
        _settle(qtbot, reader)

        # ...but only the pages around the reading position were decoded.
        assert decode_spy, "the visible page was never decoded"
        assert all(t is not threading.main_thread() for _, t in decode_spy)
        decoded = {member for member, _ in decode_spy}
        assert len(decoded) <= _window_bound(reader) < 30
        assert "page000.jpg" in decoded
        assert "page029.jpg" not in decoded

    def test_scrolling_keeps_memory_bounded(self, app_window, qapp, qtbot,
                                            sample_manga, make_cbz):
        _stage_chapter(app_window, sample_manga, make_cbz, pages=30)
        app_window.show()
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)
        assert 0 in reader._shown_pages

        sb = reader._scroll.verticalScrollBar()
        assert sb.maximum() > 0
        sb.setValue(sb.maximum() // 2)
        _settle(qtbot, reader)

        first, last, _ = reader._visible_page_range()
        assert first > 2
        assert set(range(first, last + 1)) <= reader._shown_pages
        # The first page left the window: its pixmap is released.
        assert 0 not in reader._shown_pages
        assert reader._page_slots[0].pixmap().isNull()
        assert len(reader._shown_pages) <= _window_bound(reader) + 2
        assert reader._page_cache.total_bytes <= reader.PAGE_CACHE_BYTES

    def test_cache_budget_holds_while_reading_through(
            self, app_window, qapp, qtbot, sample_manga, make_cbz):
        _stage_chapter(app_window, sample_manga, make_cbz, pages=20)
        app_window.show()
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()
        reader = app_window._pages["reader"]
        reader._page_cache.max_bytes = 3 * 400 * 600 * 4
        sb = reader._scroll.verticalScrollBar()
        for step in range(1, 11):
            sb.setValue(sb.maximum() * step // 10)
            _settle(qtbot, reader)
            assert (reader._page_cache.total_bytes
                    <= reader._page_cache.max_bytes
                    or len(reader._page_cache) == 1)

    def test_single_mode_prefetches_next_pages(self, app_window, qapp,
                                               qtbot, sample_manga,
                                               make_cbz):
        _stage_chapter(app_window, sample_manga, make_cbz, pages=8)
        app_window.config.set("gui.reader_view_mode", "single")
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)
        cached = {key[0] for key in reader._page_cache.keys()}
        assert {0, 1, 2, 3} <= cached
        assert 7 not in cached

        # The prefetched page shows at once, without waiting for a worker.
        reader._go_to_page(1)
        assert not reader._page_labels[0].pixmap().isNull()

    def test_double_mode_prefetches_whole_spreads(self, app_window, qapp,
                                                  qtbot, sample_manga,
                                                  make_cbz):
        _stage_chapter(app_window, sample_manga, make_cbz, pages=12)
        app_window.config.set("gui.reader_view_mode", "double")
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)
        cached = {key[0] for key in reader._page_cache.keys()}
        assert set(range(0, 8)) <= cached
        reader._go_to_page(2)
        assert all(not lbl.pixmap().isNull() for lbl in reader._page_labels)

    def test_continuous_resume_decodes_restored_position(
            self, app_window, qapp, qtbot, sample_manga, make_cbz):
        title = _stage_chapter(app_window, sample_manga, make_cbz, pages=20)
        app_window.app_state.set_reader_position(
            title, "1", mode="continuous", scroll_ratio=0.5)
        app_window.show()
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        qapp.processEvents()  # restore is deferred one event-loop turn
        qapp.processEvents()
        reader = app_window._pages["reader"]
        sb = reader._scroll.verticalScrollBar()
        assert sb.value() == pytest.approx(sb.maximum() * 0.5,
                                           abs=sb.maximum() * 0.05)
        _settle(qtbot, reader)
        first, last, _ = reader._visible_page_range()
        assert first > 2
        assert set(range(first, last + 1)) <= reader._shown_pages
        assert 0 not in reader._shown_pages
        assert not app_window.app_state.is_chapter_read(title, "1")

    def test_previous_chapter_results_are_ignored(self, app_window, qapp,
                                                  qtbot, sample_manga,
                                                  make_cbz):
        from PySide6.QtGui import QImage
        _stage_chapter(app_window, sample_manga, make_cbz, pages=4,
                       chapter="1")
        _stage_chapter(app_window, sample_manga, make_cbz, pages=4,
                       chapter="2")
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        old_token = reader._page_loader.token
        reader._go_next_chapter()
        assert reader._chapter == "2"
        _settle(qtbot, reader)

        stale = QImage(7, 7, QImage.Format.Format_RGB32)
        key = (3, reader._page_target_w, reader._zoom_level)
        reader._page_cache.clear()
        reader._on_page_ready(old_token, *key, stale)
        assert key not in reader._page_cache
        assert reader._page_slots[3].pixmap().isNull() or \
            reader._page_slots[3].pixmap().width() != 7

    def test_failed_small_page_keeps_its_message_readable(
            self, app_window, qapp, qtbot, sample_manga, monkeypatch,
            tmp_path):
        from PySide6.QtGui import QImage
        from memanga.gui.pages import reader_pages

        def tiny_cbz(pages, name):
            out = tmp_path / name
            with zipfile.ZipFile(out, "w") as zf:
                for i in range(pages):
                    zf.writestr(f"page{i:03d}.jpg", _jpg((12, 12)))
            return out
        monkeypatch.setattr(reader_pages, "decode_page",
                            lambda ref: QImage())
        _stage_chapter(app_window, sample_manga, tiny_cbz, pages=2)
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)

        label = reader._page_slots[0]
        metrics = label.fontMetrics()
        assert "couldn't be loaded" in label.text()
        assert label.height() >= metrics.height()
        assert label.width() >= min(metrics.horizontalAdvance(label.text()),
                                    reader._page_target_w)
        # The next page moved down with it.
        assert reader._page_offsets[1] >= (reader._page_offsets[0]
                                           + label.height())

    def test_failed_page_shows_placeholder_and_is_not_retried(
            self, app_window, qapp, qtbot, sample_manga, make_cbz,
            monkeypatch):
        from PySide6.QtGui import QImage
        from memanga.gui.pages import reader_pages
        calls = []

        def broken(ref):
            calls.append(ref.member)
            return QImage()
        monkeypatch.setattr(reader_pages, "decode_page", broken)
        _stage_chapter(app_window, sample_manga, make_cbz, pages=3)
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)

        assert 0 in reader._failed_pages
        assert "couldn't be loaded" in reader._page_slots[0].text()
        before = len(calls)
        reader._update_page_window()
        _settle(qtbot, reader)
        assert len(calls) == before

    def test_leaving_the_reader_releases_pages(self, app_window, qapp,
                                               qtbot, sample_manga,
                                               make_cbz):
        _stage_chapter(app_window, sample_manga, make_cbz, pages=6)
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)
        assert len(reader._page_cache)
        app_window.show_page("detail", manga=sample_manga)
        assert len(reader._page_cache) == 0
        assert not reader._shown_pages
        assert not reader._page_loader.has_pending()

    def test_close_stops_the_page_workers(self, app_window, qapp, tmp_path):
        from memanga.gui.pages.reader_pages import index_chapter_folder
        (tmp_path / "p.png").write_bytes(_png())
        ref = index_chapter_folder(tmp_path)[0]
        reader = app_window._pages["reader"]
        app_window.close()
        assert reader._page_loader.request(0, ref, 800, 1.0) is False

    def test_zoom_resizes_continuous_pages_in_place(self, app_window, qapp,
                                                    qtbot, sample_manga,
                                                    make_cbz):
        _stage_chapter(app_window, sample_manga, make_cbz, pages=12)
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)
        labels = list(reader._page_labels)
        old_width = labels[0].width()
        old_key = (0, reader._page_target_w, reader._zoom_level)
        assert old_key in reader._page_cache

        reader._zoom_in()
        # Same widgets, new sizes: no per-page widget rebuild on zoom.
        assert reader._page_labels == labels
        assert labels[0].width() > old_width
        assert reader._image_layout.indexOf(reader._next_footer) >= 0

        _settle(qtbot, reader)
        new_key = (0, reader._page_target_w, reader._zoom_level)
        assert new_key != old_key and new_key in reader._page_cache
        assert 0 in reader._shown_pages
        assert reader._page_slots[0].pixmap().size() == labels[0].size()


class TestRemoveAfterReadWithLazyPages:
    """Pages are decoded from the chapter file on demand, so
    remove-after-read (#104) deletes it only once the reader leaves the
    chapter, after its page jobs are cancelled — exactly once."""

    def _finish_chapter(self, app_window, qapp, qtbot, sample_manga,
                        make_cbz, chapters=("1",)):
        app_window.config.set("reader.remove_after_read", True)
        for chapter in chapters:
            title = _stage_chapter(app_window, sample_manga, make_cbz,
                                   pages=20, chapter=chapter)
        app_window.show()
        app_window.show_page("reader", manga=sample_manga,
                             chapter=chapters[0])
        qapp.processEvents()
        reader = app_window._pages["reader"]
        _settle(qtbot, reader)
        sb = reader._scroll.verticalScrollBar()
        assert sb.maximum() > 0
        sb.setValue(sb.maximum())
        qapp.processEvents()
        _settle(qtbot, reader)
        artifact = (Path(app_window.config.download_dir) / title
                    / f"{title} - Chapter {chapters[0]}.cbz")
        return reader, title, artifact

    def test_revisit_after_zoom_renders_until_the_chapter_is_left(
            self, app_window, qapp, qtbot, sample_manga, make_cbz):
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz)
        # Marked read at once; the file stays while the chapter is open.
        assert app_window.app_state.is_chapter_read(title, "1")
        assert artifact.exists()
        assert app_window.app_state.is_chapter_downloaded(title, "1")
        assert 0 not in reader._shown_pages  # first page was released

        reader._zoom_in()  # new size: no cached pixmap fits any more
        reader._scroll.verticalScrollBar().setValue(0)
        qapp.processEvents()
        _settle(qtbot, reader)
        assert 0 in reader._shown_pages
        assert not reader._page_slots[0].pixmap().isNull()
        assert not reader._failed_pages

        app_window.show_page("detail", manga=sample_manga)
        assert not artifact.exists()
        assert not app_window.app_state.is_chapter_downloaded(title, "1")
        assert app_window.app_state.is_chapter_read(title, "1")

    def test_removal_runs_exactly_once(self, app_window, qapp, qtbot,
                                       sample_manga, make_cbz, monkeypatch):
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz)
        calls = []
        real_remove = reader._remove_after_read
        monkeypatch.setattr(reader, "_remove_after_read",
                            lambda *args: (calls.append(args),
                                           real_remove(*args)))
        app_window.show_page("detail", manga=sample_manga)
        app_window.show_page("reader", manga=sample_manga, chapter="1")
        app_window.show_page("detail", manga=sample_manga)
        app_window.close()
        assert calls == [(title, "1", artifact)]
        assert not artifact.exists()

    def test_next_chapter_removes_the_finished_one(self, app_window, qapp,
                                                   qtbot, sample_manga,
                                                   make_cbz):
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz,
            chapters=("1", "2"))
        assert artifact.exists()
        reader._go_next_chapter()
        assert reader._chapter == "2"
        assert reader._images
        assert not artifact.exists()
        assert not app_window.app_state.is_chapter_downloaded(title, "1")
        assert app_window.app_state.is_chapter_downloaded(title, "2")

    def test_close_removes_before_the_final_state_flush(
            self, app_window, qapp, qtbot, sample_manga, make_cbz):
        from memanga.state import State
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz)
        app_window.close()
        assert not artifact.exists()
        saved = State(app_window.config.config_dir)
        assert not saved.is_chapter_downloaded(title, "1")
        assert saved.is_chapter_read(title, "1")

    def test_removal_waits_for_a_running_decode(self, app_window, qapp,
                                                qtbot, sample_manga,
                                                make_cbz, monkeypatch):
        from memanga.gui.pages import reader_pages
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz)
        events = []
        gate = threading.Event()
        real_decode = reader_pages.decode_page

        def slow_decode(ref):
            events.append("decode-start")
            gate.wait(5)
            image = real_decode(ref)
            events.append("decode-end")  # the file read has finished
            return image
        monkeypatch.setattr(reader_pages, "decode_page", slow_decode)
        real_remove = reader._remove_after_read
        monkeypatch.setattr(reader, "_remove_after_read",
                            lambda *args: (events.append("remove"),
                                           real_remove(*args)))

        reader._zoom_in()  # new size: workers start decoding again
        qtbot.waitUntil(lambda: "decode-start" in events, timeout=5000)
        release = threading.Timer(0.3, gate.set)
        release.start()
        try:
            app_window.show_page("detail", manga=sample_manga)
        finally:
            gate.set()
            release.cancel()

        removed_at = events.index("remove")
        before = events[:removed_at]
        assert before.count("decode-start") == before.count("decode-end")
        assert "decode-start" not in events[removed_at:]
        assert not artifact.exists()

    def _hold_decodes(self, reader, monkeypatch, qtbot):
        """Make the next page decodes block until the returned gate is
        set, and start them."""
        from memanga.gui.pages import reader_pages
        gate = threading.Event()
        started = threading.Event()
        real_decode = reader_pages.decode_page

        def stuck_decode(ref):
            started.set()
            gate.wait(30)
            return real_decode(ref)
        monkeypatch.setattr(reader_pages, "decode_page", stuck_decode)
        reader._zoom_in()  # new size: workers start decoding again
        qtbot.waitUntil(started.is_set, timeout=5000)
        return gate

    @pytest.mark.slow
    def test_removal_past_the_deadline_is_kept_and_retried(
            self, app_window, qapp, qtbot, sample_manga, make_cbz,
            monkeypatch):
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz)
        # Pages left showing the chapter must refresh once it is removed.
        refreshed = []
        detail = app_window._pages["detail"]
        library = app_window._pages["library"]
        monkeypatch.setattr(
            detail, "_refresh_chapter_list",
            lambda: refreshed.append(("detail", app_window.app_state
                                      .is_chapter_downloaded(title, "1"))))
        monkeypatch.setattr(
            library, "_on_check_done",
            lambda: refreshed.append(("library", app_window.app_state
                                      .is_chapter_downloaded(title, "1"))))
        gate = self._hold_decodes(reader, monkeypatch, qtbot)
        try:
            began = time.monotonic()
            app_window.show_page("detail", manga=sample_manga)
            # The UI waited out the deadline, but no longer.
            assert time.monotonic() - began < reader.REMOVAL_WAIT_S + 1.5
            # A decode still reads the file: nothing deleted, nothing lost.
            assert artifact.exists()
            assert app_window.app_state.is_chapter_downloaded(title, "1")
            assert reader._removal_queue == [(title, "1", artifact)]
            assert reader._removal_timer.isActive()
        finally:
            gate.set()

        qtbot.waitUntil(lambda: not artifact.exists(), timeout=10000)
        assert not app_window.app_state.is_chapter_downloaded(title, "1")
        assert app_window.app_state.is_chapter_read(title, "1")
        assert reader._removal_queue == []
        assert not reader._removal_timer.isActive()
        # Still on Detail, no navigation: both pages heard of the removal
        # and saw the chapter as no longer downloaded.
        qtbot.waitUntil(lambda: ("detail", False) in refreshed
                        and ("library", False) in refreshed, timeout=5000)
        assert detail._stats_label.text().startswith("Downloaded: 0 chapters")

    @pytest.mark.slow
    def test_reopening_a_queued_chapter_keeps_it_until_left_again(
            self, app_window, qapp, qtbot, sample_manga, make_cbz,
            monkeypatch):
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz)
        gate = self._hold_decodes(reader, monkeypatch, qtbot)
        try:
            app_window.show_page("detail", manga=sample_manga)
            assert reader._removal_queue == [(title, "1", artifact)]
            # The held decode ends just before the reopen, so the loader
            # is idle during the reopen's bounded wait: the exact window
            # in which the queued removal used to delete the file.
            gate.set()
            app_window.show_page("reader", manga=sample_manga, chapter="1")
        finally:
            gate.set()

        assert artifact.exists()
        assert reader._removal_queue == []
        assert reader._pending_removal == (title, "1", artifact)
        assert len(reader._images) == 20
        _settle(qtbot, reader)
        # The zoom that started the held decodes moved the end of the
        # chapter below the read threshold, so Back saved a resume
        # position (#106) and the reopen restores it. Whatever position
        # that is, the pages on screen come from the kept file.
        first, last, _ = reader._visible_page_range()
        assert set(range(first, last + 1)) <= reader._shown_pages
        assert not reader._page_slots[first].pixmap().isNull()
        assert not reader._failed_pages
        assert app_window.app_state.is_chapter_downloaded(title, "1")
        assert app_window.app_state.is_chapter_read(title, "1")
        # The retry timer leaves the open chapter alone.
        qtbot.wait(3 * reader.REMOVAL_RETRY_MS)
        assert artifact.exists()

        app_window.show_page("detail", manga=sample_manga)
        assert not artifact.exists()
        assert not app_window.app_state.is_chapter_downloaded(title, "1")
        assert app_window.app_state.is_chapter_read(title, "1")

    @pytest.mark.slow
    def test_close_with_a_stuck_decode_keeps_the_chapter(
            self, app_window, qapp, qtbot, sample_manga, make_cbz,
            monkeypatch):
        reader, title, artifact = self._finish_chapter(
            app_window, qapp, qtbot, sample_manga, make_cbz)
        gate = self._hold_decodes(reader, monkeypatch, qtbot)
        try:
            app_window.close()
        finally:
            gate.set()
        # No retry is possible after close: file and state stay in step,
        # and the user is told why.
        assert artifact.exists()
        assert app_window.app_state.is_chapter_downloaded(title, "1")
        assert app_window.app_state.is_chapter_read(title, "1")
        assert any("still in use" in n["message"]
                   for n in app_window.app_state.get_notifications())
        assert reader._removal_queue == []


class TestChapterRemovedRefresh:
    """chapter_removed, published after a deferred remove-after-read,
    refreshes pages already showing the manga without navigation."""

    def test_visible_detail_refreshes_hero_and_list(self, app_window, qapp,
                                                    sample_manga,
                                                    monkeypatch):
        title = sample_manga["title"]
        app_window.config.set("manga", [sample_manga])
        for chapter in ("1", "2"):
            app_window.app_state.add_downloaded_chapter(title, chapter)
        app_window.show()
        app_window.show_page("detail", manga=sample_manga)
        detail = app_window._pages["detail"]
        assert detail._stats_label.text().startswith("Downloaded: 2 chapters")
        lists = []
        real_refresh = detail._refresh_chapter_list
        monkeypatch.setattr(detail, "_refresh_chapter_list",
                            lambda: (lists.append(True), real_refresh()))

        app_window.app_state.remove_downloaded_chapter(title, "1")
        app_window.events.publish("chapter_removed",
                                  {"title": "Other Manga", "chapter": "1"})
        app_window.events.poll()
        assert lists == []  # another manga: untouched

        app_window.events.publish("chapter_removed",
                                  {"title": title, "chapter": "1"})
        app_window.events.poll()
        assert lists == [True]
        assert detail._stats_label.text().startswith("Downloaded: 1 chapters")

    def test_library_schedules_its_refresh(self, app_window, qapp,
                                           sample_manga, monkeypatch):
        library = app_window._pages["library"]
        calls = []
        monkeypatch.setattr(library, "_on_check_done",
                            lambda: calls.append(True))
        app_window.events.publish("chapter_removed",
                                  {"title": sample_manga["title"],
                                   "chapter": "1"})
        app_window.events.poll()
        assert calls == [True]
