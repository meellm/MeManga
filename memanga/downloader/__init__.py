"""
Downloader for MeManga

Handles:
1. Checking sources for new chapters using scrapers (``updates``)
2. Downloading chapter images (``chapter``)
3. Converting to PDF, EPUB, CBZ or image folders (``formats``)
4. Running the user's post-processing hook (``post_processing``)
5. Cleanup of browser resources (``browsers``) and managed download
   folders (``folders``)
6. Backup source fallback (wait N days before using backup)

This package module is the stable import surface: callers import from
``memanga.downloader`` and the names below are re-exported from the
focused submodules that own them. ``get_scraper`` and
``list_supported_sources`` are re-exported from ``memanga.scrapers`` for
code that imported them from here.

Re-exports are bindings to the owners' objects, so rebinding a name on this
module does not change what the owners use. Patch or configure a name on
the module that looks it up:

- ``POST_PROCESSING_TIMEOUT``: set it on
  ``memanga.downloader.post_processing``. Assigning
  ``memanga.downloader.POST_PROCESSING_TIMEOUT`` is not a supported control.
- ``get_scraper``: patch it on ``memanga.downloader.updates`` (update checks
  and backup lookup) and ``memanga.downloader.chapter`` (chapter downloads).
"""

from ..scrapers import get_scraper, list_supported_sources
from .browsers import _cleanup_at_exit, restart_browsers
from .chapter import DEFAULT_PAGE_RETRIES, OutputFormat, download_chapter
from .errors import DownloaderError
from .folders import (UnsafeDownloadPathError, delete_manga_downloads,
                      find_manga_downloads, rename_manga_downloads)
from .formats import (_EPUB_CONTAINER_XML, _EPUB_PAGE_TEMPLATE,
                      _build_comicinfo_xml, _image_to_jpeg_bytes,
                      _images_to_cbz, _images_to_epub, _images_to_folder,
                      _images_to_pdf, _parse_comicinfo_date)
from .naming import (_download_folder_key, _format_chapter_number,
                     _get_extension, _sanitize_filename)
from .post_processing import (_POST_PROCESSING_PLACEHOLDER_RE,
                              POST_PROCESSING_TIMEOUT, _drain_after_timeout,
                              _run_post_processing,
                              _run_post_processing_command,
                              _split_post_processing_command,
                              _substitute_post_processing_placeholders,
                              _terminate_process_tree)
from .sources import (ChapterWithSource, _configure_mangadex, _extract_source,
                      _get_sources_from_manga, get_supported_sources)
from .updates import (DEFAULT_FALLBACK_DELAY_DAYS, _find_chapter_on_backup,
                      _max_cached_chapter, check_for_updates)

__all__ = [
    "DEFAULT_FALLBACK_DELAY_DAYS",
    "DEFAULT_PAGE_RETRIES",
    "POST_PROCESSING_TIMEOUT",
    "ChapterWithSource",
    "DownloaderError",
    "OutputFormat",
    "UnsafeDownloadPathError",
    "check_for_updates",
    "delete_manga_downloads",
    "download_chapter",
    "find_manga_downloads",
    "get_supported_sources",
    "rename_manga_downloads",
    "restart_browsers",
]
