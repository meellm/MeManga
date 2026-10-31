"""
Lazy page loading for the reader (issue #389).

Opening a chapter only *indexes* it: page order plus each page's natural
size, read from the image headers. Pixels are decoded per page on demand,
on a small worker pool, and only for the pages around the reading
position. The reader keeps a bounded cache of the scaled results.

Thread rules (Qt): QImage may be created and scaled on any thread; QPixmap
only on the GUI thread. Workers therefore hand QImages back through a
queued signal, and PixmapCache is touched from the GUI thread only. Qt PDF
runs every PDFium call under one process-wide lock (PDFium is not
reentrant), so each decode opens, renders and drops its own QPdfDocument
on its worker thread.
"""

from __future__ import annotations

import logging
import posixpath
import threading
import zipfile
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import unquote
from xml.etree import ElementTree

from PySide6.QtCore import (QBuffer, QByteArray, QIODevice, QObject, QSize,
                            Qt, Signal)
from PySide6.QtGui import QImage, QImageReader, QPainter, QPixmap

from ...image_limits import MAX_PAGE_PIXELS, check_image_size

logger = logging.getLogger(__name__)

# Pages are held to the pixel limit for page images (issue #386), checked
# against each image's header before decoding. Qt's own allocation limit
# (256 MiB by default, which refuses tall webtoon strips the downloader
# accepts) is raised to the same budget, 4 bytes per pixel, and stays the
# backstop for images whose header gives no size. Process-wide in Qt.
QImageReader.setAllocationLimit(-(-MAX_PAGE_PIXELS * 4 // (1 << 20)))

# Every extension the archive writer can name a page with
# (downloader/formats/cbz.py); Qt's content probe below still decides
# whether a page is actually readable.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif",
                    ".bmp", ".tif", ".tiff", ".avif", ".heic")

# Enough to reach the size field of every supported format, including
# JPEGs with large EXIF/ICC segments. Rarer cases fall back to the whole
# entry.
_HEADER_BYTES = 64 * 1024

# Render resolution of whole PDF pages, the one the reader has always used
# for them, and a cap on the longest side so an oversized page (a poster,
# a broken page box) can't exhaust memory.
_PDF_DPI = 150
_PDF_MAX_SIDE = 8192

# Backend kinds a PageRef can name. A PDF page that is exactly one image
# covering the whole page, which is how MeManga writes every page, shows
# that image as stored (pikepdf, no re-encode, native size). Every other
# PDF page is rendered whole with Qt PDF (PDFium, part of PySide6): text,
# drawings, annotations, rotation and cropping appear as in a PDF viewer.
# A page with form fields is rendered the same way after qpdf has burned
# the fields into it. PyMuPDF is never used, even when installed, because
# it is AGPL-licensed (issue #382).
KIND_ZIP = "zip"
KIND_IMAGE = "image"
KIND_PDF_PIKEPDF = "pdf-pikepdf"
KIND_PDF_RENDER = "pdf-render"
KIND_PDF_FORM = "pdf-form"
_RENDERED_PDF_KINDS = (KIND_PDF_RENDER, KIND_PDF_FORM)


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


# Largest container.xml or package document read to find an EPUB cover;
# real ones are a few KiB. Anything bigger is skipped, not parsed.
_EPUB_XML_MAX = 4 << 20


def _local_name(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _read_epub_xml(zf: zipfile.ZipFile, name: str):
    info = zf.getinfo(name)
    if info.file_size > _EPUB_XML_MAX:
        raise ValueError(f"{name} is too large")
    return ElementTree.fromstring(zf.read(info))


def _epub_package_path(zf: zipfile.ZipFile) -> Optional[str]:
    """The package document (OPF) named by META-INF/container.xml."""
    root = _read_epub_xml(zf, "META-INF/container.xml")
    rootfiles = [el for el in root.iter() if _local_name(el.tag) == "rootfile"
                 and el.get("full-path")]
    for el in rootfiles:
        if el.get("media-type") == "application/oebps-package+xml":
            return el.get("full-path")
    return rootfiles[0].get("full-path") if rootfiles else None


def _declared_epub_covers(zf: zipfile.ZipFile) -> Set[str]:
    """Archive members the package declares as the cover image: the EPUB 3
    manifest property cover-image, and the EPUB 2 <meta name="cover">
    that Kindle reads. Manifest hrefs are URLs relative to the OPF."""
    opf = _epub_package_path(zf)
    if not opf:
        return set()
    root = _read_epub_xml(zf, opf)
    base = posixpath.dirname(opf)
    items: Dict[str, str] = {}
    covers: Set[str] = set()
    cover_ids: Set[str] = set()
    for el in root.iter():
        name = _local_name(el.tag)
        if name == "item" and el.get("href"):
            href = unquote(el.get("href").split("#", 1)[0])
            member = posixpath.normpath(posixpath.join(base, href))
            if el.get("id"):
                items[el.get("id")] = member
            if "cover-image" in (el.get("properties") or "").split():
                covers.add(member)
        elif name == "meta" and el.get("name") == "cover":
            cover_ids.add(el.get("content", ""))
    covers.update(items[i] for i in cover_ids if i in items)
    return covers


def _epub_cover_members(zf: zipfile.ZipFile, names: Iterable[str]) -> Set[str]:
    """Members that may be the cover image. Without a declared cover (or a
    readable package), a member named cover.* is taken as one."""
    try:
        covers = _declared_epub_covers(zf)
    except Exception as e:
        logger.debug("Couldn't read the EPUB cover metadata: %s", e)
        covers = set()
    if covers:
        return covers
    return {n for n in names if Path(n).stem.lower() == "cover"}


def _same_member(zf: zipfile.ZipFile, a: str, b: str) -> bool:
    """True when two members hold the same bytes. Size and CRC-32 from
    the archive directory settle most pairs without reading either; a
    member that can't be read counts as different, so it stays a page."""
    ia, ib = zf.getinfo(a), zf.getinfo(b)
    if ia.file_size != ib.file_size or ia.CRC != ib.CRC:
        return False
    try:
        return zf.read(ia) == zf.read(ib)
    except Exception:
        return False


def _index_epub(filepath: Path) -> List[PageRef]:
    """Image pages of an EPUB. A cover image identical to the first page,
    which is what an EPUB without a separate cover holds (MeManga writes
    the first page again as its cover), is shown once; a distinct cover
    stays a page of its own."""
    with zipfile.ZipFile(filepath, "r") as zf:
        names = sorted(zf.namelist())
        pages = _index_zip(filepath, names)
        covers = _epub_cover_members(zf, names)
        first = next((p for p in pages if p.member not in covers), None)
        if first is None:
            return pages
        return [p for p in pages if p.member not in covers
                or not _same_member(zf, p.member, first.member)]


def _page_attr(page_obj, key):
    """A page attribute, inherited from the page tree when the page
    itself doesn't set it (Rotate, MediaBox, CropBox, Resources)."""
    node = page_obj
    for _ in range(64):  # bound a malformed /Parent loop
        if node is None:
            return None
        if key in node:
            return node[key]
        node = node.get("/Parent")
    return None


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 0.01


def _single_image_page(page) -> Optional[str]:
    """Name of the image XObject when the PDF page is exactly that image
    stretched over the whole page, as MeManga (img2pdf) writes every
    page, so showing the image as stored loses nothing. None for any
    other page: text, drawings, annotations, several or masked images,
    rotation, cropping, other placement, or a content stream pikepdf
    can't parse."""
    import pikepdf
    obj = page.obj
    if obj.get("/Annots"):
        return None
    rotate = _page_attr(obj, "/Rotate")
    if rotate is not None and int(rotate) % 360:
        return None
    media = _page_attr(obj, "/MediaBox")
    if media is None or len(media) != 4:
        return None
    box = [float(v) for v in media]
    crop = _page_attr(obj, "/CropBox")
    if crop is not None and [float(v) for v in crop] != box:
        return None
    names = list(page.images)
    if len(names) != 1:
        return None
    raw = page.images[names[0]]
    if any(key in raw for key in ("/SMask", "/Mask", "/Decode")):
        return None
    if bool(raw.get("/ImageMask", False)):
        return None
    try:
        instructions = pikepdf.parse_content_stream(page)
    except Exception:
        return None
    if [str(ins.operator) for ins in instructions] != ["q", "cm", "Do", "Q"]:
        return None
    matrix = instructions[1].operands
    target = instructions[2].operands
    if len(matrix) != 6 or len(target) != 1 or str(target[0]) != names[0]:
        return None
    a, b, c, d, e, f = (float(v) for v in matrix)
    x0, x1 = sorted(box[0::2])
    y0, y1 = sorted(box[1::2])
    if not (_close(a, x1 - x0) and _close(d, y1 - y0) and _close(b, 0)
            and _close(c, 0) and _close(e, x0) and _close(f, y0)):
        return None
    return names[0]


def _has_form_fields(page) -> bool:
    import pikepdf
    for annot in page.obj.get("/Annots", None) or ():
        if (isinstance(annot, pikepdf.Dictionary)
                and annot.get("/Subtype") == pikepdf.Name.Widget):
            return True
    return False


def _open_qt_pdf(source):
    """A loaded QPdfDocument for a file path or an open QIODevice, which
    must outlive the document. Both load synchronously: a local file and
    an in-memory buffer are complete when load() returns."""
    from PySide6.QtPdf import QPdfDocument
    doc = QPdfDocument()
    doc.load(str(source) if isinstance(source, Path) else source)
    if doc.status() != QPdfDocument.Status.Ready:
        error = doc.error()
        doc.close()
        raise ValueError(f"Qt PDF can't open it ({error.name})")
    return doc


def _render_size(doc, page: int) -> Tuple[int, int]:
    """Pixel size of a whole page at _PDF_DPI. Qt PDF gives the visible
    page (crop box, page rotation applied) in points."""
    points = doc.pagePointSize(page)
    width = points.width() * _PDF_DPI / 72
    height = points.height() * _PDF_DPI / 72
    if width <= 0 or height <= 0:
        return (0, 0)
    shrink = min(1.0, _PDF_MAX_SIDE / max(width, height))
    return (max(1, round(width * shrink)), max(1, round(height * shrink)))


def _index_pdf(filepath: Path) -> List[PageRef]:
    """One reader page per PDF page. Image pages report their image's
    size; whole-page renders their size at _PDF_DPI, read by Qt PDF only
    when the file has such pages."""
    import pikepdf
    pages = []
    with pikepdf.open(str(filepath)) as pdf:
        for i, page in enumerate(pdf.pages):
            name = _single_image_page(page)
            if name is None:
                kind = (KIND_PDF_FORM if _has_form_fields(page)
                        else KIND_PDF_RENDER)
                pages.append(PageRef(filepath, kind, page=i))
                continue
            raw = page.images[name]
            try:
                width = int(raw.get("/Width", 0))
                height = int(raw.get("/Height", 0))
            except Exception:
                width = height = 0
            pages.append(PageRef(filepath, KIND_PDF_PIKEPDF, member=name,
                                 page=i, width=width, height=height))
    if any(p.kind in _RENDERED_PDF_KINDS for p in pages):
        try:
            doc = _open_qt_pdf(filepath)
        except Exception as e:
            # Pages keep no size; their decode fails and shows as such.
            logger.warning("Couldn't read page sizes of %s: %s", filepath, e)
        else:
            try:
                sized = []
                for p in pages:
                    if p.kind in _RENDERED_PDF_KINDS:
                        width, height = _render_size(doc, p.page)
                        p = replace(p, width=width, height=height)
                    sized.append(p)
                pages = sized
            finally:
                doc.close()
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
            return _index_epub(filepath)
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
    """One embedded PDF image, decoded with pikepdf.

    A plain JPEG stream goes to QImage as stored. Anything else is
    unpacked by pikepdf (filters, palettes, colour spaces) and its pixels
    copied straight into a QImage — never re-encoded to another format.
    An image over the pixel limit is refused before either."""
    import pikepdf
    check_image_size(int(raw.get("/Width", 0)), int(raw.get("/Height", 0)))
    pdf_image = pikepdf.PdfImage(raw)
    if _is_plain_jpeg(pdf_image):
        img = QImage()
        if img.loadFromData(raw.read_raw_bytes()):
            return img
    img = _qimage_from_pil(pdf_image.as_pil_image())
    if img.isNull():
        raise ValueError(f"unsupported PDF image {pdf_image!r}")
    return img


# Annotation flags (PDF 32000-1:2008, 12.5.3) that keep a field off screen.
_ANNOT_HIDDEN = 1 << 1
_ANNOT_NO_VIEW = 1 << 5


def _field_attr(widget, key):
    """A form field attribute, inherited from the parent fields when the
    widget doesn't set it (/FT, /V, ...)."""
    node = widget
    for _ in range(64):  # bound a malformed /Parent loop
        if node is None:
            return None
        if key in node:
            return node[key]
        node = node.get("/Parent")
    return None


# Button field flag (PDF 32000-1:2008, 12.7.4.2.1): a radio button group.
_FIELD_RADIO = 1 << 15


def _visible_widgets(page):
    """The page's form field widgets that are shown on screen."""
    import pikepdf
    for annot in page.obj.get("/Annots", None) or ():
        if (isinstance(annot, pikepdf.Dictionary)
                and annot.get("/Subtype") == pikepdf.Name.Widget
                and not int(annot.get("/F", 0))
                & (_ANNOT_HIDDEN | _ANNOT_NO_VIEW)):
            yield annot


def _normal_appearance(annot):
    """The widget's normal appearance: a stream, a dictionary of
    appearance states (buttons), or None."""
    import pikepdf
    ap = annot.get("/AP")
    return ap.get("/N") if isinstance(ap, pikepdf.Dictionary) else None


def _button_state(annot):
    """The appearance state a button widget shows: its /AS, else the state
    its field's value (/V, inherited from the parent field) selects. A
    radio button whose appearances lack the group's value is not the
    selected one, so it shows /Off."""
    import pikepdf
    state = annot.get("/AS")
    if state is not None:
        return state
    value = _field_attr(annot, "/V")
    if not isinstance(value, pikepdf.Name):
        return None
    normal = _normal_appearance(annot)
    if (isinstance(normal, pikepdf.Dictionary) and value not in normal
            and int(_field_attr(annot, "/Ff") or 0) & _FIELD_RADIO):
        return pikepdf.Name.Off
    return value


def _select_button_states(page):
    """Give each button widget without /AS the state its field's value
    selects, when it has an appearance for it. qpdf draws a button's
    state dictionary only through /AS; the copy is in memory only."""
    import pikepdf
    for annot in _visible_widgets(page):
        if (_field_attr(annot, "/FT") != pikepdf.Name.Btn
                or "/AS" in annot):
            continue
        state = _button_state(annot)
        normal = _normal_appearance(annot)
        if (state is not None and isinstance(normal, pikepdf.Dictionary)
                and state in normal):
            annot.AS = state


def _undrawable_filled_fields(page) -> int:
    """How many visible, filled-in form fields on *page* have no
    appearance stream to draw. Their value would be lost without a trace:
    PDF viewers draw a field from its appearance, and qpdf only generates
    one when the form sets NeedAppearances (and never for buttons). A
    button is filled when the state it shows (/AS, else its value) is not
    /Off."""
    import pikepdf
    count = 0
    for annot in _visible_widgets(page):
        normal = _normal_appearance(annot)
        if _field_attr(annot, "/FT") == pikepdf.Name.Btn:
            state = _button_state(annot)
            if state is None or state == pikepdf.Name.Off:
                continue
            if isinstance(normal, pikepdf.Stream) or (
                    isinstance(normal, pikepdf.Dictionary)
                    and state in normal):
                continue
        else:
            value = _field_attr(annot, "/V")
            if value is None or str(value) == "":
                continue
            if isinstance(normal, pikepdf.Stream):
                continue
        count += 1
    return count


def _flattened_form_page(ref: PageRef) -> bytes:
    """The PDF page alone, with its form fields burned into its content.

    Qt PDF draws no form fields: PDFium shows them only through its
    form-fill layer, which Qt PDF doesn't run. qpdf merges each visible
    field's appearance stream into the page, after generating text and
    choice fields' appearances when the form asks for that
    (NeedAppearances). All of it happens in memory; the file on disk is
    only read. A visible, filled-in field that still has no appearance
    raises, so its page shows as failed rather than without the field."""
    import io
    import pikepdf
    with pikepdf.open(str(ref.source)) as pdf:
        for i in reversed(range(len(pdf.pages))):
            if i != ref.page:
                del pdf.pages[i]
        pdf.generate_appearance_streams()
        _select_button_states(pdf.pages[0])
        missing = _undrawable_filled_fields(pdf.pages[0])
        if missing:
            raise ValueError(f"{missing} filled-in form field(s) on the page "
                             f"have no appearance to draw")
        pdf.flatten_annotations("screen")
        out = io.BytesIO()
        pdf.save(out)
    return out.getvalue()


def _render_pdf_page(ref: PageRef) -> QImage:
    """The whole PDF page, annotations and form fields included, on
    white paper."""
    from PySide6.QtPdf import QPdfDocumentRenderOptions
    buf = None
    if ref.kind == KIND_PDF_FORM:
        buf = QBuffer()
        buf.setData(QByteArray(_flattened_form_page(ref)))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        doc, index = _open_qt_pdf(buf), 0
    else:
        doc, index = _open_qt_pdf(ref.source), ref.page
    try:
        size = ((ref.width, ref.height) if ref.width and ref.height
                else _render_size(doc, index))
        options = QPdfDocumentRenderOptions()
        options.setRenderFlags(
            QPdfDocumentRenderOptions.RenderFlag.Annotations)
        page = doc.render(index, QSize(*size), options)
    finally:
        doc.close()
        if buf is not None:
            buf.close()
    if page.isNull():
        raise ValueError("Qt PDF couldn't render the page")
    # Qt PDF leaves every part of the page nothing paints transparent.
    img = QImage(page.size(), QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.white)
    painter = QPainter(img)
    painter.drawImage(0, 0, page)
    painter.end()
    return img


def _read_image(device) -> QImage:
    """The image on *device* (a file name or an open QIODevice), refused
    before decoding when its header declares more than the pixel limit."""
    reader = QImageReader(device)
    size = reader.size()
    if size.isValid():
        check_image_size(size.width(), size.height())
    return reader.read()


def _decode(ref: PageRef) -> QImage:
    if ref.kind == KIND_ZIP:
        with zipfile.ZipFile(ref.source, "r") as zf:
            data = zf.read(ref.member)
        buf = QBuffer()
        buf.setData(QByteArray(data))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        try:
            return _read_image(buf)
        finally:
            buf.close()
    if ref.kind == KIND_IMAGE:
        return _read_image(str(ref.source))
    if ref.kind == KIND_PDF_PIKEPDF:
        import pikepdf
        with pikepdf.open(str(ref.source)) as pdf:
            return _decode_pdf_image(pdf.pages[ref.page].images[ref.member])
    if ref.kind in _RENDERED_PDF_KINDS:
        return _render_pdf_page(ref)
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
