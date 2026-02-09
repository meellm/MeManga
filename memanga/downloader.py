"""
Downloader for MeManga

Handles:
1. Checking sources for new chapters using scrapers
2. Downloading chapter images
3. Converting to PDF or EPUB
4. Cleanup
5. Backup source fallback (wait N days before using backup)
"""

import io
import tempfile
import shutil
import uuid
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

OutputFormat = Literal["pdf", "epub"]

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
        )
        self.source = source
        self.source_url = source_url
        self.is_backup = is_backup


def _extract_source(url: str) -> str:
    """Extract source domain from URL."""
    parsed = urlparse(url)
    return parsed.netloc.replace("www.", "")


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


def check_for_updates(manga: Dict[str, Any], state: State) -> List[ChapterWithSource]:
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
    
    Returns:
        List of ChapterWithSource objects (includes source info)
    """
    title = manga["title"]
    sources = _get_sources_from_manga(manga)
    fallback_delay_days = manga.get("fallback_delay_days", DEFAULT_FALLBACK_DELAY_DAYS)
    
    if not sources:
        raise DownloaderError(f"No sources configured for '{title}'")
    
    # Get last downloaded chapter
    last_chapter = state.get_last_chapter(title)
    last_num = float(last_chapter) if last_chapter else 0.0
    
    # Results to return
    chapters_to_download: List[ChapterWithSource] = []
    
    # Track what we found on each source
    primary_chapters: Dict[str, Chapter] = {}  # chapter_num -> Chapter
    backup_chapters: Dict[str, Tuple[Chapter, str, str]] = {}  # chapter_num -> (Chapter, source, url)
    
    # Check each source
    for i, src in enumerate(sources):
        source = src["source"]
        url = src["url"]
        is_primary = (i == 0)
        
        try:
            scraper = get_scraper(source)
            all_chapters = scraper.get_chapters(url)
        except ValueError as e:
            # Unsupported source - skip but warn
            print(f"  [Warning] Unsupported source '{source}': {e}")
            continue
        except Exception as e:
            # Failed to fetch - skip but warn
            print(f"  [Warning] Failed to fetch from {source}: {e}")
            continue
        
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
    
    return sorted(chapters_to_download)


def download_chapter(
    manga: Dict[str, Any],
    chapter: Chapter,
    output_dir: Path,
    output_format: OutputFormat = "pdf",
    state: Optional[State] = None,
) -> Optional[Path]:
    """
    Download a chapter and convert to PDF or EPUB.
    
    Args:
        manga: Manga entry from config
        chapter: Chapter to download (can be ChapterWithSource)
        output_dir: Directory to save the file
        output_format: "pdf" or "epub"
        state: State manager (for clearing pending backup after download)
    
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
        
        # Download images
        image_paths = []
        for i, url in enumerate(page_urls):
            ext = _get_extension(url)
            img_path = temp_path / f"page_{i:03d}{ext}"
            
            if scraper.download_image(url, img_path):
                image_paths.append(img_path)
            else:
                print(f"  Warning: Failed to download page {i+1}")
        
        if not image_paths:
            raise DownloaderError("Failed to download any pages")
        
        # Convert to output format
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_title = _sanitize_filename(title)
        
        # Zero-pad chapter numbers for proper sorting
        chapter_str = _format_chapter_number(chapter.number)
        
        if output_format == "epub":
            output_path = output_dir / f"{safe_title} - Chapter {chapter_str}.epub"
            try:
                _images_to_epub(image_paths, output_path, title, chapter.number)
            except Exception as e:
                raise DownloaderError(f"Failed to create EPUB: {e}")
        else:
            output_path = output_dir / f"{safe_title} - Chapter {chapter_str}.pdf"
            try:
                _images_to_pdf(image_paths, output_path)
            except Exception as e:
                raise DownloaderError(f"Failed to create PDF: {e}")
        
        return output_path


def _images_to_epub(image_paths: List[Path], output_path: Path, title: str, chapter_num: str):
    """Convert a list of images to a fixed-layout EPUB with cover."""
    book = epub.EpubBook()
    
    # Set metadata
    book_id = str(uuid.uuid4())
    book.set_identifier(book_id)
    book.set_title(f"{title} - Chapter {chapter_num}")
    book.set_language('en')
    book.add_author(title)  # Use manga title as author for organization
    
    # Add cover image (first page)
    if image_paths:
        cover_path = image_paths[0]
        with Image.open(cover_path) as img:
            # Convert to JPEG for cover
            buf = io.BytesIO()
            if img.mode in ('RGBA', 'P', 'LA'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                rgb_img.save(buf, format='JPEG', quality=95)
            else:
                img.convert('RGB').save(buf, format='JPEG', quality=95)
            
            book.set_cover("cover.jpg", buf.getvalue())
    
    # Create spine and pages
    spine = ['nav']
    
    for i, img_path in enumerate(image_paths):
        # Read and process image
        with Image.open(img_path) as img:
            width, height = img.size
            
            # Convert to JPEG/PNG bytes
            buf = io.BytesIO()
            if img.mode in ('RGBA', 'P', 'LA'):
                # Keep transparency for PNG
                img.save(buf, format='PNG')
                img_format = 'png'
                media_type = 'image/png'
            else:
                img.convert('RGB').save(buf, format='JPEG', quality=95)
                img_format = 'jpg'
                media_type = 'image/jpeg'
            
            img_data = buf.getvalue()
        
        # Create image item
        img_name = f"page_{i:03d}.{img_format}"
        img_item = epub.EpubItem(
            uid=f"img_{i}",
            file_name=f"images/{img_name}",
            media_type=media_type,
            content=img_data
        )
        book.add_item(img_item)
        
        # Create HTML page for this image (fixed layout)
        html_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
    <title>Page {i + 1}</title>
    <meta name="viewport" content="width={width}, height={height}"/>
    <style>
        html, body {{
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
        }}
        img {{
            width: 100%;
            height: auto;
            display: block;
        }}
    </style>
</head>
<body>
    <img src="images/{img_name}" alt="Page {i + 1}"/>
</body>
</html>'''
        
        page = epub.EpubHtml(
            title=f'Page {i + 1}',
            file_name=f'page_{i:03d}.xhtml',
            lang='en'
        )
        page.content = html_content.encode('utf-8')
        book.add_item(page)
        spine.append(page)
    
    # Add navigation
    book.toc = []
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    
    # Set spine
    book.spine = spine
    
    # Write EPUB
    epub.write_epub(str(output_path), book)


def _images_to_pdf(image_paths: List[Path], output_path: Path):
    """Convert a list of images to a single PDF."""
    # Convert images to RGB if needed (img2pdf doesn't support all formats)
    processed_images = []
    
    for img_path in image_paths:
        try:
            with Image.open(img_path) as img:
                # Convert to RGB if necessary
                if img.mode in ('RGBA', 'P', 'LA'):
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    
                    # Save to bytes
                    buf = io.BytesIO()
                    rgb_img.save(buf, format='JPEG', quality=95)
                    processed_images.append(buf.getvalue())
                elif img.mode != 'RGB':
                    rgb_img = img.convert('RGB')
                    buf = io.BytesIO()
                    rgb_img.save(buf, format='JPEG', quality=95)
                    processed_images.append(buf.getvalue())
                else:
                    processed_images.append(img_path.read_bytes())
        except Exception as e:
            print(f"  Warning: Could not process {img_path}: {e}")
    
    if not processed_images:
        raise DownloaderError("No images could be processed")
    
    # Create PDF
    pdf_bytes = img2pdf.convert(processed_images)
    output_path.write_bytes(pdf_bytes)


def _get_extension(url: str) -> str:
    """Get file extension from URL."""
    url_lower = url.lower().split('?')[0]
    for ext in ['.webp', '.png', '.jpg', '.jpeg', '.gif']:
        if ext in url_lower:
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
