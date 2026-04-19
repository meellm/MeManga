"""
Downloader for MeManga

Handles:
1. Checking sources for new chapters using scrapers
2. Downloading chapter images
3. Converting to PDF, EPUB, or CBZ
4. Cleanup
5. Backup source fallback (wait N days before using backup)
"""

import io
import atexit
import tempfile
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Dict, Any, Literal, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlparse

import img2pdf
from PIL import Image
from ebooklib import epub

from .state import State
from .scrapers import get_scraper, list_supported_sources
from .scrapers.base import Chapter


def restart_browsers():
    """Restart any browser instances to free memory."""
    try:
        from .scrapers.mangafire import VRFGenerator
        VRFGenerator().restart()
    except Exception:
        pass

    try:
        from .scrapers.playwright_base import PlaywrightScraper
        PlaywrightScraper.cleanup()
    except Exception:
        pass


def _cleanup_at_exit():
    """Clean up browser resources on exit."""
    restart_browsers()


atexit.register(_cleanup_at_exit)

OutputFormat = Literal["pdf", "epub", "cbz", "zip", "jpg", "png", "webp"]

# Default days to wait before falling back to backup source
DEFAULT_FALLBACK_DELAY_DAYS = 2


class DownloaderError(Exception):
    """Base exception for downloader errors."""
    pass


class ChapterWithSource(Chapter):
    """Chapter with source info for multi-source support."""
    
    def __init__(self, chapter: Chapter, source: str, source_url: str, is_backup: bool = False):
        super().__init__(
            number=chapter.number,
            title=chapter.title,
            url=chapter.url,
            date=chapter.date,
        )
        self.source = source
        self.source_url = source_url
        self.is_backup = is_backup


def _extract_source(url: str) -> str:
    """Extract source domain from URL."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _get_sources_from_manga(manga: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Get list of sources from manga config.
    Supports both old format (single source) and new format (sources array).
    
    Returns: List of dicts with 'source' and 'url' keys
    """
    # New format: sources array
    if "sources" in manga:
        sources = []
        for s in manga["sources"]:
            if isinstance(s, dict):
                url = s.get("url", "")
                source = s.get("source") or _extract_source(url)
                sources.append({"source": source, "url": url})
            elif isinstance(s, str):
                # Just a URL string
                sources.append({"source": _extract_source(s), "url": s})
        return sources
    
    # Old format: single source/url
    return [{
        "source": manga.get("source", ""),
        "url": manga.get("url", ""),
    }]


def check_for_updates(
    manga: Dict[str, Any],
    state: State,
    from_chapter: Optional[float] = None,
    return_all: bool = False,
):
    """
    Check if a manga has new chapters, with backup source support.

    Logic:
    1. Check primary source first
    2. If new chapter on primary → return it
    3. If no new chapter → check backup source(s)
    4. If backup has new chapter:
       - Already in pending_backup? Check if fallback_delay passed
         - Yes → return it (download from backup)
         - No → skip (still waiting)
       - Not in pending_backup? Add it, skip (start waiting)
    5. If primary gets the chapter later, we prefer primary

    Args:
        manga: Manga entry from config with title, sources (or url/source)
        state: State manager to check last downloaded chapter
        from_chapter: Override starting chapter (for downloading from scratch)
        return_all: If True, return a tuple ``(new_chapters, all_chapters)``
            where ``all_chapters`` is the full chapter list from the primary
            source wrapped as :class:`ChapterWithSource` (used by the GUI
            Detail page to show every chapter as Read/Download). When False
            (default), returns just the filtered new-chapter list — preserves
            the original CLI signature.

    Returns:
        ``List[ChapterWithSource]`` (default) or
        ``Tuple[List[ChapterWithSource], List[ChapterWithSource]]`` when
        ``return_all=True``.
    """
    title = manga["title"]
    sources = _get_sources_from_manga(manga)
    fallback_delay_days = manga.get("fallback_delay_days", DEFAULT_FALLBACK_DELAY_DAYS)
    
    if not sources:
        raise DownloaderError(f"No sources configured for '{title}'")
    
    # Get starting chapter - use from_chapter if provided, else last downloaded
    if from_chapter is not None:
        # Subtract small amount so --from 1 includes chapter 1
        last_num = from_chapter - 0.001
    else:
        last_chapter = state.get_last_chapter(title)
        last_num = float(last_chapter) if last_chapter else 0.0
    
    # Results to return
    chapters_to_download: List[ChapterWithSource] = []

    # Track what we found on each source
    primary_chapters: Dict[str, Chapter] = {}  # chapter_num -> Chapter
    backup_chapters: Dict[str, Tuple[Chapter, str, str]] = {}  # chapter_num -> (Chapter, source, url)

    # Full chapter list from the primary source (every chapter, downloaded or not).
    # Used by the GUI Detail page when return_all=True so it can render every
    # chapter as Read or Download without re-scraping.
    primary_all: List[ChapterWithSource] = []

    # Check each source
    source_errors = []
    sources_checked = 0
    for i, src in enumerate(sources):
        source = src["source"]
        url = src["url"]
        is_primary = (i == 0)

        try:
            scraper = get_scraper(source)
            all_chapters = scraper.get_chapters(url)
            sources_checked += 1
        except ValueError as e:
            # Unsupported source - skip but warn
            source_errors.append(f"{source}: {e}")
            print(f"  [Warning] Unsupported source '{source}': {e}")
            continue
        except Exception as e:
            # Failed to fetch - skip but warn
            source_errors.append(f"{source}: {e}")
            print(f"  [Warning] Failed to fetch from {source}: {e}")
            continue

        # Capture the full chapter list from the primary source for the
        # Detail-page cache. Backup sources are intentionally skipped here —
        # we don't want backup-only chapters polluting the canonical list.
        if is_primary:
            primary_all = [
                ChapterWithSource(ch, source, url, is_backup=False)
                for ch in all_chapters
            ]

        # Filter to new chapters
        new_chapters = [
            ch for ch in all_chapters
            if ch.numeric > last_num and not state.is_chapter_downloaded(title, ch.number)
        ]

        for ch in new_chapters:
            ch_num = ch.number

            if is_primary:
                primary_chapters[ch_num] = ch
            else:
                # Only track if not already on primary
                if ch_num not in primary_chapters:
                    backup_chapters[ch_num] = (ch, source, url)
    
    # If ALL sources failed, raise so the caller knows
    if sources_checked == 0 and source_errors:
        raise DownloaderError(
            f"All sources failed for '{title}': " + "; ".join(source_errors)
        )

    # Process primary chapters first (always download these)
    for ch_num, ch in primary_chapters.items():
        primary_src = sources[0]
        chapters_to_download.append(
            ChapterWithSource(ch, primary_src["source"], primary_src["url"], is_backup=False)
        )
        # Clear any pending backup for this chapter (primary caught up)
        state.clear_pending_backup(title, ch_num)
    
    # Process backup chapters
    now = datetime.now()
    for ch_num, (ch, backup_source, backup_url) in backup_chapters.items():
        # Skip if we're already downloading from primary
        if ch_num in primary_chapters:
            continue
        
        pending = state.get_pending_backup(title, ch_num)
        
        if pending:
            # Check if fallback delay has passed
            first_seen = datetime.fromisoformat(pending["first_seen"])
            days_waiting = (now - first_seen).days
            
            if days_waiting >= fallback_delay_days:
                # Delay passed, download from backup
                chapters_to_download.append(
                    ChapterWithSource(ch, backup_source, backup_url, is_backup=True)
                )
                # Note: We'll clear pending_backup after successful download
            # else: still waiting, do nothing
        else:
            # First time seeing this on backup, start waiting
            state.set_pending_backup(title, ch_num, backup_source, ch.url)

    new_sorted = sorted(chapters_to_download)
    if return_all:
        return new_sorted, sorted(primary_all)
    return new_sorted


def download_chapter(
    manga: Dict[str, Any],
    chapter: Chapter,
    output_dir: Path,
    output_format: OutputFormat = "pdf",
    state: Optional[State] = None,
    progress_callback=None,
    naming_template: Optional[str] = None,
) -> Optional[Path]:
    """
    Download a chapter and convert to PDF or EPUB.

    Args:
        manga: Manga entry from config
        chapter: Chapter to download (can be ChapterWithSource)
        output_dir: Directory to save the file
        output_format: "pdf" or "epub"
        state: State manager (for clearing pending backup after download)
        progress_callback: Optional callable(current, total) for progress updates

    Returns:
        Path to downloaded file, or None if failed
    """
    title = manga["title"]
    
    # Get source from chapter if available (ChapterWithSource), else from manga config
    if isinstance(chapter, ChapterWithSource):
        source = chapter.source
        is_backup = chapter.is_backup
    else:
        sources = _get_sources_from_manga(manga)
        source = sources[0]["source"] if sources else ""
        is_backup = False
    
    # Get scraper
    try:
        scraper = get_scraper(source)
    except ValueError as e:
        raise DownloaderError(f"Unsupported source: {e}")
    
    # Create temp directory for images
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Get page URLs
        try:
            page_urls = scraper.get_pages(chapter.url)
        except Exception as e:
            raise DownloaderError(f"Failed to get pages: {e}")
        
        if not page_urls:
            raise DownloaderError("No pages found for chapter")
        
        # Download images concurrently
        image_paths = []
        download_tasks = []
        for i, url in enumerate(page_urls):
            ext = _get_extension(url)
            img_path = temp_path / f"page_{i:03d}{ext}"
            download_tasks.append((i, url, img_path))

        results: Dict[int, Path] = {}
        total_pages = len(download_tasks)
        completed_count = 0
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(scraper.download_image, url, img_path): (idx, img_path)
                for idx, url, img_path in download_tasks
            }
            for future in as_completed(futures):
                idx, img_path = futures[future]
                try:
                    if future.result():
                        results[idx] = img_path
                    else:
                        print(f"  Warning: Failed to download page {idx+1}")
                except Exception:
                    print(f"  Warning: Failed to download page {idx+1}")
                completed_count += 1
                if progress_callback:
                    progress_callback(completed_count, total_pages)

        # Preserve page order
        image_paths = [results[i] for i in sorted(results)]
        
        if not image_paths:
            raise DownloaderError("Failed to download any pages")

        # Download cover image for EPUB
        cover_path = None
        if output_format == "epub":
            cover_url = manga.get("cover_url")
            if not cover_url:
                # Try to fetch cover from the manga page
                try:
                    manga_url = manga.get("url", "")
                    if not manga_url:
                        sources = _get_sources_from_manga(manga)
                        manga_url = sources[0]["url"] if sources else ""
                    if manga_url:
                        cover_url = scraper.get_cover_url(manga_url)
                except Exception:
                    pass
            if cover_url:
                cover_path = temp_path / "cover_art.jpg"
                try:
                    if not scraper.download_image(cover_url, cover_path):
                        cover_path = None
                except Exception:
                    cover_path = None

        # Convert to output format
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_title = _sanitize_filename(title)

        # Zero-pad chapter numbers for proper sorting
        chapter_str = _format_chapter_number(chapter.number)

        # Build filename from template
        template = naming_template or "{title} - Chapter {chapter}"
        base_name = _sanitize_filename(
            template.replace("{title}", title)
                    .replace("{chapter}", chapter_str)
                    .replace("{source}", source)
        )

        if output_format == "epub":
            output_path = output_dir / f"{base_name}.epub"
            try:
                _images_to_epub(image_paths, output_path, title, chapter.number, cover_path)
            except Exception as e:
                raise DownloaderError(f"Failed to create EPUB: {e}")
        elif output_format == "cbz":
            output_path = output_dir / f"{base_name}.cbz"
            try:
                _images_to_cbz(image_paths, output_path)
            except Exception as e:
                raise DownloaderError(f"Failed to create CBZ: {e}")
        elif output_format == "zip":
            output_path = output_dir / f"{base_name}.zip"
            try:
                _images_to_cbz(image_paths, output_path)  # Reuse CBZ logic (same ZIP format)
            except Exception as e:
                raise DownloaderError(f"Failed to create ZIP: {e}")
        elif output_format in ("jpg", "png", "webp"):
            chapter_folder = output_dir / safe_title / f"Chapter {chapter_str}"
            try:
                _images_to_folder(image_paths, chapter_folder, output_format)
            except Exception as e:
                raise DownloaderError(f"Failed to save images: {e}")
            output_path = chapter_folder  # Return the directory path
        else:
            output_path = output_dir / f"{base_name}.pdf"
            try:
                _images_to_pdf(image_paths, output_path)
            except Exception as e:
                raise DownloaderError(f"Failed to create PDF: {e}")
        
        return output_path


def _image_to_jpeg_bytes(img_path: Path) -> tuple:
    """Convert any image to JPEG bytes suitable for EPUB/Kindle.

    Returns (jpeg_bytes, width, height).
    """
    img = Image.open(img_path)
    try:
        width, height = img.size
        # Flatten transparency onto white background
        if img.mode in ('RGBA', 'P', 'LA', 'PA'):
            rgba = img.convert('RGBA')
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.split()[3])
            rgba.close()
            img.close()
            img = bg
        elif img.mode != 'RGB':
            converted = img.convert('RGB')
            img.close()
            img = converted
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=95)
        return buf.getvalue(), width, height
    finally:
        img.close()


def _images_to_epub(
    image_paths: List[Path],
    output_path: Path,
    title: str,
    chapter_num: str,
    cover_image_path: Optional[Path] = None,
):
    """Convert images to a fixed-layout EPUB compatible with Kindle.

    Args:
        image_paths: Ordered list of page image paths.
        output_path: Where to write the .epub file.
        title: Manga title.
        chapter_num: Chapter number string.
        cover_image_path: Optional separate cover image. Falls back to first page.
    """
    book = epub.EpubBook()

    # ── Metadata ──
    book_id = str(uuid.uuid4())
    book.set_identifier(book_id)
    full_title = f"{title} - Chapter {chapter_num}"
    book.set_title(full_title)
    book.set_language('en')
    book.add_author(title)

    # Fixed-layout metadata (required for Kindle to render as image pages)
    book.add_metadata(None, 'meta', 'pre-paginated', {'property': 'rendition:layout'})
    book.add_metadata(None, 'meta', 'auto', {'property': 'rendition:orientation'})
    book.add_metadata(None, 'meta', 'none', {'property': 'rendition:spread'})

    # ── Cover image ──
    cover_src = cover_image_path if cover_image_path and cover_image_path.exists() else (
        image_paths[0] if image_paths else None
    )
    if cover_src:
        cover_data, cw, ch = _image_to_jpeg_bytes(cover_src)
        # Manually add cover item with proper metadata for Kindle
        cover_item = epub.EpubItem(
            uid='cover-image',
            file_name='images/cover.jpg',
            media_type='image/jpeg',
            content=cover_data,
        )
        book.add_item(cover_item)
        # Kindle recognises this meta tag to find the cover
        book.add_metadata('OPF', 'meta', '', {
            'name': 'cover',
            'content': 'cover-image',
        })

        # Cover XHTML page
        cover_html = epub.EpubHtml(
            title='Cover',
            file_name='cover.xhtml',
            lang='en',
        )
        cover_html.content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Cover</title>
<meta name="viewport" content="width={cw}, height={ch}"/>
<style>html,body{{margin:0;padding:0;width:100%;height:100%}}
img{{width:100%;height:auto;display:block}}</style></head>
<body><img src="images/cover.jpg" alt="Cover"/></body></html>'''.encode('utf-8')
        book.add_item(cover_html)

    # ── Page images ──
    spine = []
    if cover_src:
        spine.append(cover_html)

    for i, img_path in enumerate(image_paths):
        img_data, width, height = _image_to_jpeg_bytes(img_path)

        img_name = f"page_{i:03d}.jpg"
        img_item = epub.EpubItem(
            uid=f"img_{i}",
            file_name=f"images/{img_name}",
            media_type='image/jpeg',
            content=img_data,
        )
        book.add_item(img_item)

        page_html = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Page {i + 1}</title>
<meta name="viewport" content="width={width}, height={height}"/>
<style>html,body{{margin:0;padding:0;width:100%;height:100%}}
img{{width:100%;height:auto;display:block}}</style></head>
<body><img src="images/{img_name}" alt="Page {i + 1}"/></body></html>'''

        page = epub.EpubHtml(
            title=f'Page {i + 1}',
            file_name=f'page_{i:03d}.xhtml',
            lang='en',
        )
        page.content = page_html.encode('utf-8')
        book.add_item(page)
        spine.append(page)

    # ── Navigation ──
    book.toc = []
    book.add_item(epub.EpubNcx())
    nav = epub.EpubNav()
    book.add_item(nav)

    # Spine: nav hidden, then pages in order
    book.spine = [nav] + spine

    epub.write_epub(str(output_path), book)


def _images_to_pdf(image_paths: List[Path], output_path: Path):
    """Convert a list of images to a single PDF."""
    processed_images = []

    for img_path in image_paths:
        try:
            jpeg_data, _, _ = _image_to_jpeg_bytes(img_path)
            processed_images.append(jpeg_data)
        except Exception as e:
            print(f"  Warning: Could not process {img_path}: {e}")

    if not processed_images:
        raise DownloaderError("No images could be processed")

    pdf_bytes = img2pdf.convert(processed_images)
    output_path.write_bytes(pdf_bytes)


def _images_to_cbz(image_paths: List[Path], output_path: Path):
    """Convert a list of images to a CBZ (Comic Book ZIP) archive.

    Images are stored as-is (no re-encoding) with sequential names
    for correct reading order.
    """
    import zipfile

    if not image_paths:
        raise DownloaderError("No images to archive")

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_STORED) as cbz:
        for i, img_path in enumerate(image_paths):
            ext = img_path.suffix.lower() or '.jpg'
            cbz.write(img_path, f"page_{i:03d}{ext}")


def _images_to_folder(image_paths: List[Path], output_dir: Path, img_format: str):
    """Save images to a folder, converting to the specified format.

    Args:
        image_paths: Downloaded source images
        output_dir: Chapter folder to save into (e.g., downloads/Manga/Chapter 001/)
        img_format: Target format - "jpg", "png", or "webp"
    """
    if not image_paths:
        raise DownloaderError("No images to save")

    output_dir.mkdir(parents=True, exist_ok=True)

    pillow_format_map = {
        "jpg": ("JPEG", ".jpg", {"quality": 95}),
        "png": ("PNG", ".png", {}),
        "webp": ("WEBP", ".webp", {"quality": 90}),
    }

    pil_format, ext, save_kwargs = pillow_format_map[img_format]

    for i, img_path in enumerate(image_paths):
        img = Image.open(img_path)
        try:
            # JPEG requires RGB (no alpha channel)
            if pil_format == "JPEG" and img.mode in ('RGBA', 'P', 'LA', 'PA'):
                rgba = img.convert('RGBA')
                bg = Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[3])
                rgba.close()
                img.close()
                img = bg
            elif pil_format == "JPEG" and img.mode != 'RGB':
                converted = img.convert('RGB')
                img.close()
                img = converted
            elif pil_format in ("PNG", "WEBP") and img.mode not in ('RGB', 'RGBA'):
                converted = img.convert('RGB')
                img.close()
                img = converted

            out_path = output_dir / f"{i:03d}{ext}"
            img.save(out_path, format=pil_format, **save_kwargs)
        finally:
            img.close()


def _get_extension(url: str) -> str:
    """Get file extension from URL path (not substring match)."""
    from posixpath import splitext
    path = url.split('?')[0].split('#')[0]
    _, ext = splitext(path)
    ext = ext.lower()
    if ext in ('.webp', '.png', '.jpg', '.jpeg', '.gif'):
        return ext
    return '.jpg'


def _sanitize_filename(name: str) -> str:
    """Make a string safe for use as filename."""
    # Remove/replace invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '')
    return name.strip()[:100]  # Limit length


def _format_chapter_number(chapter_num: str) -> str:
    """
    Format chapter number for proper alphabetical sorting.
    
    - Regular chapters: stay as is (2, 3, 4...)
    - Part chapters: "2 Part 1" -> "2.01", "2 Part 2" -> "2.02"
    - Decimal chapters: stay as is (2.5 -> 2.5)
    
    Sorting result: 2 < 2.01 < 2.02 < 2.5 < 3 (correct!)
    """
    import re
    
    # Check for "Part X" pattern (case insensitive)
    part_match = re.match(r'^(\d+)\s*[Pp]art\s*(\d+)(.*)$', chapter_num)
    if part_match:
        main_num = part_match.group(1)
        part_num = part_match.group(2).zfill(2)  # Zero-pad to 2 digits
        rest = part_match.group(3)  # Any trailing text
        return f"{main_num}.{part_num}{rest}"
    
    # Return as-is for regular and decimal chapters
    return chapter_num


def get_supported_sources() -> List[str]:
    """Get list of supported source domains."""
    return list_supported_sources()
