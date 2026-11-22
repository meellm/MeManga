"""Exceptions raised by the download engine."""


class DownloaderError(Exception):
    """Base exception for downloader errors.

    Incomplete-download failures carry structured detail so callers can
    record/act on them without parsing the message string:
    ``failed_pages`` (1-indexed page numbers) and ``total_pages``.
    Both are ``None`` for errors unrelated to per-page failures.
    """

    def __init__(self, message, failed_pages=None, total_pages=None):
        super().__init__(message)
        self.failed_pages = failed_pages
        self.total_pages = total_pages
