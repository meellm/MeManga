"""CBZ/ZIP archive writer and ComicInfo.xml metadata."""

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...scrapers.base import Chapter
from ..errors import DownloaderError


# BCP 47 "undetermined" language. EPUB requires a language, so it is
# written there when neither the manga entry nor its source names one;
# ComicInfo then omits LanguageISO instead.
UNDETERMINED_LANGUAGE = "und"
# BCP 47 shape: a 2-3 letter language plus optional subtags ("pt-BR").
_LANGUAGE_TAG_RE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*", re.ASCII)
_READING_DIRECTIONS = ("rtl", "ltr", "vertical")


def _language_tag(value: Any) -> Optional[str]:
    if isinstance(value, str) and _LANGUAGE_TAG_RE.fullmatch(value.strip()):
        return value.strip()
    return None


def _reading_direction_value(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip().lower() in _READING_DIRECTIONS:
        return value.strip().lower()
    return None


def _manga_language(manga: Dict[str, Any], scraper=None) -> Optional[str]:
    """Language tag of a manga's pages, or None when unknown.

    The manga entry's ``language`` wins; otherwise the source's
    ``content_language`` is used, which only sources serving a single
    language set. Nothing is guessed.
    """
    return (_language_tag(manga.get("language"))
            or _language_tag(getattr(scraper, "content_language", None)))


def _reading_direction(manga: Dict[str, Any], scraper=None) -> Optional[str]:
    """``"rtl"``, ``"ltr"`` or ``"vertical"`` for a manga, or None when
    unknown: the manga entry's ``reading_direction`` wins over the
    source's."""
    return (_reading_direction_value(manga.get("reading_direction"))
            or _reading_direction_value(getattr(scraper, "reading_direction", None)))


def _parse_comicinfo_date(date_str: Optional[str]) -> Optional[Tuple[int, int, int]]:
    """Best-effort parse of a chapter/source date into (year, month, day).

    Chapter dates arrive in many shapes across scrapers (ISO 8601 from API
    sources like ``publishAt``, free-form text elsewhere). Returns ``None``
    when nothing usable can be extracted so the caller simply omits the
    Year/Month/Day fields.
    """
    if not date_str:
        return None
    text = str(date_str).strip()
    if not text:
        return None

    # ISO 8601 first (covers the trailing "...Z" suffix common to API sources).
    try:
        iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
        dt = datetime.fromisoformat(iso_text)
        return dt.year, dt.month, dt.day
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y",
        "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.year, dt.month, dt.day
        except ValueError:
            continue
    return None


def _build_comicinfo_xml(
    manga: Dict[str, Any],
    chapter: Chapter,
    page_count: int,
    scraper=None,
) -> bytes:
    """Build a ComicInfo.xml document from already-known metadata.

    Only fields MeManga already has on hand (the tracked manga config and
    the ``Chapter`` object) are written; no extra network requests are
    made. Optional fields with no data are omitted entirely. Serialization
    and XML escaping are handled by ElementTree.

    ``scraper`` is the chapter's source; its declared language and
    reading direction are used when the manga entry names none.
    ``LanguageISO`` is written only for a known language, and
    ``Manga=YesAndRightToLeft`` only for a known right-to-left title:
    manhwa and webtoons read left to right or top to bottom, and ComicInfo
    has no value for those, so an unknown or non-RTL title gets no
    ``Manga`` field. ``Count`` (the series' total number of chapters) is
    not written: MeManga does not know it, and readers such as Kavita and
    Komga take it as final and mark the series complete.
    """
    from xml.etree.ElementTree import Element, SubElement, tostring

    root = Element("ComicInfo", {
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
    })

    def add(tag: str, value: Any):
        if value is None:
            return
        text = str(value).strip()
        if not text:
            return
        SubElement(root, tag).text = text

    chapter_title = getattr(chapter, "title", None)
    add("Title", chapter_title or f"Chapter {chapter.number}")
    add("Series", manga.get("title"))
    add("Number", chapter.number)

    add("Summary", manga.get("description"))

    parsed = _parse_comicinfo_date(getattr(chapter, "date", None))
    if parsed:
        year, month, day = parsed
        add("Year", year)
        add("Month", month)
        add("Day", day)

    add("Writer", manga.get("author"))
    # MangaDex credit: the scanlation group(s) that translated this chapter.
    add("Translator", ", ".join(getattr(chapter, "group_names", [])))

    # Web: prefer the specific chapter URL, fall back to the manga URL.
    add("Web", getattr(chapter, "url", "") or manga.get("url", ""))
    add("PageCount", page_count)
    add("LanguageISO", _manga_language(manga, scraper))
    if _reading_direction(manga, scraper) == "rtl":
        add("Manga", "YesAndRightToLeft")

    return tostring(root, encoding="utf-8", xml_declaration=True)


# Archive entry extension of each encoded image format, recognised by its
# leading bytes: the formats the scrapers' page check sniffs
# (scrapers/base.looks_like_image) plus TIFF. Checked in order; BMP's
# two-byte mark is the weakest, so it comes last.
_PAGE_SIGNATURES = (
    (".jpg", lambda h: h.startswith(b"\xff\xd8\xff")),
    (".png", lambda h: h.startswith(b"\x89PNG\r\n\x1a\n")),
    (".gif", lambda h: h.startswith((b"GIF87a", b"GIF89a"))),
    (".webp", lambda h: h.startswith(b"RIFF") and h[8:12] == b"WEBP"),
    (".avif", lambda h: h[4:12] in (b"ftypavif", b"ftypavis")),
    (".heic", lambda h: h[4:12] in (b"ftypheic", b"ftypheix")),
    (".tif", lambda h: h.startswith((b"II*\x00", b"MM\x00*"))),
    (".bmp", lambda h: h.startswith(b"BM")),
)
# Extension for a Pillow format name where Pillow registers several and
# one is the usual choice. The first entries keep the names the
# signatures above give; PPM (which Pillow also opens for .pbm/.pgm/.pnm)
# and JPEG 2000 (.j2k/.jpc/...) get their common names.
_PILLOW_EXTENSIONS = {
    "JPEG": ".jpg", "MPO": ".jpg", "PNG": ".png", "GIF": ".gif",
    "WEBP": ".webp", "AVIF": ".avif", "HEIF": ".heic", "TIFF": ".tif",
    "BMP": ".bmp", "PPM": ".ppm", "JPEG2000": ".jp2",
}


def _pillow_extension(fmt: str) -> Optional[str]:
    """Extension for a format Pillow identified, or None when Pillow
    gives no unambiguous one.

    In order: the table above; the format's own name when Pillow
    registers it (ICO -> .ico, TGA -> .tga); the only extension Pillow
    registers for it. Never a guess among several aliases.
    """
    from PIL import Image

    if fmt in _PILLOW_EXTENSIONS:
        return _PILLOW_EXTENSIONS[fmt]
    registered = sorted(ext for ext, owner in Image.registered_extensions().items()
                        if owner == fmt)
    own = "." + fmt.lower()
    if own in registered:
        return own
    if len(registered) == 1:
        return registered[0]
    return None


def archive_page_extensions() -> frozenset:
    """Every extension ``_images_to_cbz`` can give a page here: the
    signature formats plus each format this Pillow build can open."""
    from PIL import Image

    Image.init()
    exts = {ext for ext, _ in _PAGE_SIGNATURES}
    exts.update(_PILLOW_EXTENSIONS.values())
    for fmt in Image.OPEN:
        ext = _pillow_extension(fmt)
        if ext:
            exts.add(ext)
    return frozenset(exts)


def _page_extension(path: Path, page_no: int) -> str:
    """Archive extension for the image in ``path``, from its encoded bytes.

    The common formats are recognised from their leading bytes. Anything
    else the page check accepted is identified by Pillow from its header
    (nothing is decoded or re-encoded), which also covers containers
    the signatures miss, such as AVIF with a "mif1" major brand. The
    download URL and the temp file's suffix say nothing reliable about
    the bytes, so they are not used. A page neither can name raises.
    """
    with open(path, "rb") as fh:
        head = fh.read(16)
    for ext, matches in _PAGE_SIGNATURES:
        if matches(head):
            return ext

    from PIL import Image

    try:
        with Image.open(path) as img:
            fmt = img.format
    except Exception as e:
        raise DownloaderError(
            f"Page {page_no} ({Path(path).name}) is not a recognised image; "
            f"archive not written"
        ) from e
    ext = _pillow_extension(fmt) if fmt else None
    if ext is None:
        raise DownloaderError(
            f"Page {page_no} ({Path(path).name}) is a {fmt} image with no "
            f"standard file extension to archive it under; archive not written"
        )
    return ext


def _images_to_cbz(
    image_paths: List[Path],
    output_path: Path,
    comicinfo_xml: Optional[bytes] = None,
    credit: Optional[str] = None,
):
    """Convert a list of images to a CBZ (Comic Book ZIP) archive.

    Images are stored as-is (no re-encoding) with sequential names
    for correct reading order. Each name's extension follows the page's
    encoded format, not the name it was saved under. Every page is
    identified before the archive is opened, so an unrecognised or
    missing page leaves no new or truncated archive behind.

    When ``comicinfo_xml`` is provided it is written to the archive root as
    ``ComicInfo.xml`` so offline libraries and e-readers can read chapter
    metadata. Page names and order are unaffected.
    """
    import zipfile

    if not image_paths:
        raise DownloaderError("No images to archive")

    names = [f"page_{i:03d}{_page_extension(img_path, i + 1)}"
             for i, img_path in enumerate(image_paths)]

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_STORED) as cbz:
        for img_path, name in zip(image_paths, names):
            cbz.write(img_path, name)
        if comicinfo_xml is not None:
            cbz.writestr("ComicInfo.xml", comicinfo_xml)
        if credit:
            cbz.writestr("Source.txt", credit + "\n")
