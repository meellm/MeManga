"""EPUB writer."""

import time
import uuid
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple
from xml.sax.saxutils import escape as _xml_escape

from .cbz import UNDETERMINED_LANGUAGE
from .images import _image_to_jpeg_bytes


_EPUB_PAGE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}" lang="{lang}">
<head><title>{title}</title>
<meta name="viewport" content="width={width}, height={height}"/>
<style>html,body{{margin:0;padding:0;width:100%;height:100%}}
img{{width:100%;height:auto;display:block}}</style></head>
<body><img src="{src}" alt="{title}"/></body></html>
"""

_EPUB_CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _images_to_epub(
    image_paths: List[Path],
    output_path: Path,
    title: str,
    chapter_num: str,
    cover_image_path: Optional[Path] = None,
    credit: Optional[str] = None,
    author: Optional[str] = None,
    language: Optional[str] = None,
):
    """Convert images to a fixed-layout EPUB compatible with Kindle.

    Written directly with zipfile (EPUB 3 package plus an EPUB 2 NCX for
    older readers) so no third-party EPUB library is needed.

    Args:
        image_paths: Ordered list of page image paths.
        output_path: Where to write the .epub file.
        title: Manga title.
        chapter_num: Chapter number string.
        cover_image_path: Optional separate cover image. Falls back to first page.
        credit: Optional contributor credit (MangaDex scanlation groups).
        author: The manga's author, when known. Without one no creator is
            written; the manga title is not an author.
        language: BCP 47 language tag of the pages' text. When it is not
            known, "und" (undetermined) is written on the package and every
            page, since EPUB requires a language.
    """
    attr = {'"': "&quot;"}
    book_id = f"urn:uuid:{uuid.uuid4()}"
    full_title = f"{title} - Chapter {chapter_num}"
    modified = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    language = language or UNDETERMINED_LANGUAGE
    lang = _xml_escape(language, attr)

    files: List[Tuple[str, bytes]] = []  # (path inside EPUB/, content)
    manifest: List[str] = []
    spine: List[str] = []

    # ── Cover image ──
    cover_src = cover_image_path if cover_image_path and cover_image_path.exists() else (
        image_paths[0] if image_paths else None
    )
    if cover_src:
        cover_data, cw, ch = _image_to_jpeg_bytes(cover_src)
        files.append(("images/cover.jpg", cover_data))
        manifest.append('<item id="cover-image" href="images/cover.jpg" '
                        'media-type="image/jpeg" properties="cover-image"/>')
        files.append(("cover.xhtml", _EPUB_PAGE_TEMPLATE.format(
            title="Cover", width=cw, height=ch, src="images/cover.jpg",
            lang=lang,
        ).encode("utf-8")))
        manifest.append('<item id="cover" href="cover.xhtml" '
                        'media-type="application/xhtml+xml"/>')
        spine.append("cover")

    # ── Page images ──
    for i, img_path in enumerate(image_paths):
        img_data, width, height = _image_to_jpeg_bytes(img_path)
        img_name = f"page_{i:03d}.jpg"
        files.append((f"images/{img_name}", img_data))
        manifest.append(f'<item id="img_{i}" href="images/{img_name}" media-type="image/jpeg"/>')
        files.append((f"page_{i:03d}.xhtml", _EPUB_PAGE_TEMPLATE.format(
            title=f"Page {i + 1}", width=width, height=height, src=f"images/{img_name}",
            lang=lang,
        ).encode("utf-8")))
        manifest.append(f'<item id="page_{i:03d}" href="page_{i:03d}.xhtml" '
                        'media-type="application/xhtml+xml"/>')
        spine.append(f"page_{i:03d}")

    # ── Navigation (single entry pointing at the first page) ──
    first_href = f"{spine[0]}.xhtml" if spine else "nav.xhtml"
    title_text = _xml_escape(full_title)
    files.append(("nav.xhtml", f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}" lang="{lang}">
<head><title>{title_text}</title></head>
<body><nav epub:type="toc" id="toc"><ol><li><a href="{first_href}">{title_text}</a></li></ol></nav></body></html>
""".encode("utf-8")))
    manifest.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
    files.append(("toc.ncx", f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<head><meta name="dtb:uid" content="{_xml_escape(book_id, attr)}"/></head>
<docTitle><text>{title_text}</text></docTitle>
<navMap><navPoint id="np_1" playOrder="1"><navLabel><text>{title_text}</text></navLabel><content src="{first_href}"/></navPoint></navMap>
</ncx>
""".encode("utf-8")))
    manifest.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
    if not spine:
        spine.append("nav")

    # ── Package document ──
    # Fixed-layout metadata is required for Kindle to render image pages;
    # the name="cover" meta is how Kindle finds the cover.
    manifest_xml = "\n    ".join(manifest)
    spine_xml = "\n    ".join(f'<itemref idref="{idref}"/>' for idref in spine)
    cover_meta = '\n    <meta name="cover" content="cover-image"/>' if cover_src else ""
    credit_meta = f"<dc:contributor>{_xml_escape(credit)}</dc:contributor>" if credit else ""
    author = author.strip() if isinstance(author, str) else ""
    creator_meta = (f'<dc:creator id="creator">{_xml_escape(author)}</dc:creator>'
                    if author else "")
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id" xml:lang="{lang}">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">{_xml_escape(book_id)}</dc:identifier>
    <dc:title>{title_text}</dc:title>
    <dc:language>{_xml_escape(language)}</dc:language>
    {creator_meta}
    {credit_meta}
    <meta property="dcterms:modified">{modified}</meta>
    <meta property="rendition:layout">pre-paginated</meta>
    <meta property="rendition:orientation">auto</meta>
    <meta property="rendition:spread">none</meta>{cover_meta}
  </metadata>
  <manifest>
    {manifest_xml}
  </manifest>
  <spine toc="ncx">
    {spine_xml}
  </spine>
</package>
"""

    # mimetype must be the first entry and stored uncompressed.
    with zipfile.ZipFile(output_path, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _EPUB_CONTAINER_XML,
                    compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("EPUB/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        for name, data in files:
            zf.writestr(f"EPUB/{name}", data, compress_type=zipfile.ZIP_DEFLATED)
