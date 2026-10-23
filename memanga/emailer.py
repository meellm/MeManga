"""
Email handler for MeManga - sends PDFs to Kindle

Automatically splits PDFs too large for the mail provider's email size
limit (email.max_email_mb, 25MB by default).
"""

import hashlib
import io
import logging
import shutil
import smtplib
import ssl
import tempfile
import warnings
from contextlib import contextmanager
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional
import pikepdf

from .output import register_secret

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """Base exception for email errors."""
    pass


class EmailAuthError(EmailError):
    """The SMTP server rejected the sender email or app password."""


class EmailConnectionError(EmailError):
    """The SMTP server could not be reached, the TLS handshake failed
    (including certificate checks), or the connection dropped."""


class EmailTimeoutError(EmailError):
    """The SMTP server did not answer within the timeout."""


class EmailProviderError(EmailError):
    """The SMTP server refused a command (``smtp_code`` holds its reply
    code when it sent one). When it refused the recipients,
    ``recipients`` maps each address to its ``(code, reply)``."""

    def __init__(self, message: str, smtp_code: Optional[int] = None,
                 recipients: Optional[dict] = None):
        super().__init__(message)
        self.smtp_code = smtp_code
        self.recipients = recipients


class EmailPartError(EmailError):
    """Part ``part`` of a PDF split into ``total`` parts was not sent
    (issue #364); the failure behind it is the ``__cause__``.

    ``accepted`` lists the parts the mail server accepted, in this call
    or an earlier one. Acceptance means the SMTP server took the message
    (reply 250); it does not prove the Kindle received or converted it.
    ``progress`` is what to pass back as ``send_to_kindle(progress=...)``
    so a retry of the same file sends only the parts not yet accepted.
    """

    def __init__(self, part: int, total: int, progress: Dict[str, Any],
                 detail: str):
        accepted = list(progress.get("accepted", []))
        if accepted:
            status = ("parts accepted by the mail server: "
                      + ", ".join(str(n) for n in accepted))
        else:
            status = "no parts accepted by the mail server"
        super().__init__(f"Part {part} of {total} not sent ({status}): {detail}")
        self.part = part
        self.total = total
        self.accepted = tuple(accepted)
        self.progress = progress


# Issue #361: every SMTP socket operation (connect, greeting, TLS
# handshake, login, each chunk sent, QUIT) waits at most this long.
# It bounds a stalled server, not the total transfer time.
DEFAULT_SMTP_TIMEOUT = 60
# Upper bound of email.smtp_timeout (see CONFIG_KEYS in config.py).
MAX_SMTP_TIMEOUT = 600

# Issue #366: how the connection is secured (email.smtp_tls; see
# CONFIG_KEYS in config.py). "starttls" connects in plain SMTP and
# upgrades with STARTTLS before logging in (port 587); "implicit" starts
# TLS before the SMTP greeting (RFC 8314 implicit TLS, port 465). "auto"
# uses implicit TLS on port 465 and STARTTLS on any other port. Both
# check the certificate and host name, and there is no cleartext mode.
SMTP_TLS_MODES = ("auto", "starttls", "implicit")
DEFAULT_SMTP_TLS = "auto"
IMPLICIT_TLS_PORT = 465
# Ports where implicit TLS is almost certainly the wrong choice.
STARTTLS_PORTS = (25, 587)


# Issue #363: mail providers cap the size of a whole email after encoding
# (email.max_email_mb; see CONFIG_KEYS in config.py). Base64 in 76-character
# lines turns 57 raw bytes into 78, so a raw file may use about 73% of the
# cap; RAW_ATTACHMENT_PERCENT leaves the rest for headers and MIME parts.
# Send to Kindle takes at most 50MB per email, hence the upper bound.
DEFAULT_EMAIL_SIZE_MB = 25
MIN_EMAIL_SIZE_MB = 10
MAX_EMAIL_SIZE_MB = 50
RAW_ATTACHMENT_PERCENT = 72
_MB = 1024 * 1024
EMAIL_ATTACHMENT_LIMIT = DEFAULT_EMAIL_SIZE_MB * _MB
MAX_ATTACHMENT_SIZE = 18 * _MB  # 72% of 25MB raw (~24.6MB after base64)
# split_pdf writes the parts to a temp folder with this name prefix.
SPLIT_DIR_PREFIX = "memanga_split_"


# Issue #362: the output formats Send to Kindle accepts by email. CBZ and
# ZIP archives and image folders (JPG/PNG/WEBP) are rejected by Amazon, so
# they are never sent. Every delivery path asks the two functions below.
KINDLE_FORMATS = ("pdf", "epub")
IMAGE_FOLDER_FORMATS = ("jpg", "png", "webp")


def _kindle_reason(label: str) -> str:
    return f"{label} can't be sent to Kindle; only PDF and EPUB can."


def kindle_format_error(output_format: str) -> Optional[str]:
    """None when chapters saved as ``output_format`` can be sent to
    Kindle, else why they can't (one sentence, no markup)."""
    fmt = str(output_format).strip().lower().lstrip(".")
    if fmt in KINDLE_FORMATS:
        return None
    if fmt in IMAGE_FOLDER_FORMATS:
        return _kindle_reason(f"Image folders ({fmt.upper()})")
    return _kindle_reason(f"{fmt.upper() or 'Unknown'} files")


def kindle_file_error(path: Path) -> Optional[str]:
    """None when the saved chapter at ``path`` can be sent to Kindle,
    else why not. Image formats save a folder of pages (#340)."""
    if path.is_dir():
        return _kindle_reason("Image folders")
    return kindle_format_error(path.suffix)


def _format_mb(size: int) -> str:
    """Format a byte count as MiB for user-facing messages."""
    return f"{size / (1024 * 1024):.1f}MB"


def email_size_limit(value=None) -> int:
    """The email size cap in bytes: ``value`` MB when it is a number from
    MIN_EMAIL_SIZE_MB to MAX_EMAIL_SIZE_MB, else DEFAULT_EMAIL_SIZE_MB
    (unset or hand-edited config)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        value = DEFAULT_EMAIL_SIZE_MB
    # NaN fails the comparison and infinities are out of range.
    elif not MIN_EMAIL_SIZE_MB <= value <= MAX_EMAIL_SIZE_MB:
        value = DEFAULT_EMAIL_SIZE_MB
    return int(value * _MB)


def raw_attachment_limit(email_limit: int) -> int:
    """The largest file, in bytes, that still fits in an email of at most
    ``email_limit`` bytes once base64 encoded."""
    return email_limit * RAW_ATTACHMENT_PERCENT // 100


def split_pdf(pdf_path: Path, max_size: int = MAX_ATTACHMENT_SIZE) -> List[Path]:
    """
    Split a PDF into smaller parts if it exceeds max_size.
    
    Args:
        pdf_path: Path to the PDF file
        max_size: Maximum size per part in bytes
    
    Returns:
        List of paths to PDF parts (original if no split needed)
    """
    file_size = pdf_path.stat().st_size
    
    # If under limit, return original
    if file_size <= max_size:
        return [pdf_path]
    
    # Open PDF and count pages
    with pikepdf.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        
        if total_pages <= 1:
            # Can't split single page, return as-is
            return [pdf_path]
        
        # Estimate pages per part based on file size
        avg_page_size = file_size / total_pages
        pages_per_part = max(1, int(max_size / avg_page_size) - 1)  # -1 for safety margin
        
        # Create temp directory for parts
        temp_dir = Path(tempfile.mkdtemp(prefix=SPLIT_DIR_PREFIX))
        try:
            return _write_parts(pdf, pdf_path, temp_dir, total_pages,
                                pages_per_part, max_size)
        except BaseException:
            # Issue #364: a failed split leaves no temp folder behind.
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise


def _write_parts(pdf, pdf_path: Path, temp_dir: Path, total_pages: int,
                 pages_per_part: int, max_size: int) -> List[Path]:
    """Save the pages of ``pdf`` as parts under ``max_size`` in ``temp_dir``."""
    parts = []

    part_num = 1
    start_page = 0

    while start_page < total_pages:
        end_page = min(start_page + pages_per_part, total_pages)
        
        # Create part PDF
        part_pdf = pikepdf.new()
        for page_num in range(start_page, end_page):
            part_pdf.pages.append(pdf.pages[page_num])
        
        # Save part - use decimal format (.01, .02) like source chapters
        stem = pdf_path.stem
        part_path = temp_dir / f"{stem}.{str(part_num).zfill(2)}.pdf"
        part_pdf.save(part_path)
        part_pdf.close()
        
        # Check if part is still too large and needs further splitting
        if part_path.stat().st_size > max_size and end_page - start_page > 1:
            # Reduce pages per part and try again
            pages_per_part = max(1, (end_page - start_page) // 2)
            part_path.unlink()
            continue

        parts.append(part_path)
        part_num += 1
        start_page = end_page

    return parts


def send_to_kindle(
    pdf_path: Path,
    kindle_email: str,
    sender_email: str,
    smtp_server: str,
    smtp_port: int,
    app_password: str,
    subject: Optional[str] = None,
    timeout: Optional[float] = None,
    progress: Optional[Mapping[str, Any]] = None,
    on_part_sent: Optional[Callable[[int, int], None]] = None,
    max_email_mb: Optional[float] = None,
    smtp_tls: Optional[str] = None,
) -> bool:
    """
    Send a PDF or EPUB to Kindle via email.
    
    Automatically splits PDFs too large for the email size limit.
    EPUB files are sent as-is (Kindle handles them natively). Any other
    file (CBZ, ZIP, ...) or a folder is refused before anything is sent
    (issue #362).

    Issue #364: the parts of a split PDF are sent in order over one SMTP
    session (one login), stopping at the first part that fails, which
    raises EmailPartError. The split's temp folder is removed however
    sending ends.
    
    Args:
        pdf_path: Path to the PDF or EPUB file
        kindle_email: Kindle email address (xxx@kindle.com)
        sender_email: Sender email address (must be whitelisted in Amazon)
        smtp_server: SMTP server (e.g., smtp.gmail.com)
        smtp_port: SMTP port (usually 587 for STARTTLS, 465 for implicit TLS)
        app_password: App password for email account
        subject: Email subject (optional, defaults to filename)
        timeout: Seconds each SMTP operation may wait (defaults to
            DEFAULT_SMTP_TIMEOUT)
        progress: ``EmailPartError.progress`` of an earlier attempt. Parts
            it lists as accepted are not sent again, provided the file
            content, its part count, the part size limit and the Kindle
            address are unchanged; otherwise every part is sent.
        on_part_sent: Called with ``(part, total)`` after the mail server
            accepted each part of a split PDF.
        max_email_mb: The mail provider's email size limit in MB (issue
            #363); files must fit under it once encoded. Defaults to
            DEFAULT_EMAIL_SIZE_MB.
        smtp_tls: How the connection is secured, one of SMTP_TLS_MODES
            (issue #366). Defaults to "auto" (see smtp_tls_mode).
    
    Returns:
        True if sent successfully (every part accepted by the mail server)
    
    Raises:
        EmailPartError: If a part of a split PDF was not sent
        EmailError: If sending fails otherwise
    """
    if not pdf_path.exists():
        raise EmailError(f"File not found: {pdf_path}")

    unsupported = kindle_file_error(pdf_path)
    if unsupported:
        raise EmailError(unsupported)
    
    if not kindle_email or not sender_email:
        raise EmailError("Email addresses not configured")
    
    if not app_password:
        raise EmailError("App password not configured")
    # Issue #226: never let the password reach a log line.
    register_secret(app_password)
    
    # Check file type - only split PDFs, send EPUBs as-is
    suffix = pdf_path.suffix.lower()
    is_single_file = suffix == '.epub'
    email_limit = email_size_limit(max_email_mb)
    raw_limit = raw_attachment_limit(email_limit)

    if is_single_file:
        # EPUB: check size (cannot be split)
        file_size = pdf_path.stat().st_size
        if file_size > raw_limit:
            fmt = suffix.lstrip('.').upper()
            raise EmailError(
                f"{fmt} file is {_format_mb(file_size)}, exceeding MeManga's "
                f"{_format_mb(raw_limit)} safe raw attachment limit. "
                f"Email attachments are base64 encoded, so the raw file must "
                f"stay below this limit to fit under the "
                f"{_format_mb(email_limit)} encoded email cap. "
                f"{fmt} files cannot be split. Use PDF format instead "
                f"(set in 'memanga config')."
            )
        parts = [pdf_path]
        is_split = False
    else:
        # PDF: check if needs splitting
        parts = split_pdf(pdf_path, max_size=raw_limit)
        is_split = len(parts) > 1
        try:
            _check_part_sizes(parts, raw_limit, email_limit)
        except BaseException:
            _remove_split_parts(pdf_path, parts)
            raise
        
        if is_split:
            logger.info(
                "Split into %d parts (exceeded %s safe raw attachment limit; "
                "encoded email cap is %s)",
                len(parts), _format_mb(raw_limit), _format_mb(email_limit),
            )
    
    try:
        if is_split:
            _send_parts(
                pdf_path, parts, subject or pdf_path.stem, progress,
                on_part_sent, kindle_email=kindle_email,
                sender_email=sender_email, smtp_server=smtp_server,
                smtp_port=smtp_port, app_password=app_password,
                timeout=timeout, part_limit=raw_limit, smtp_tls=smtp_tls,
            )
        else:
            _send_single_email(
                pdf_path=parts[0],
                kindle_email=kindle_email,
                sender_email=sender_email,
                smtp_server=smtp_server,
                smtp_port=smtp_port,
                app_password=app_password,
                subject=subject or pdf_path.stem,
                timeout=timeout,
                smtp_tls=smtp_tls,
            )
    finally:
        _remove_split_parts(pdf_path, parts)
    
    return True


def _check_part_sizes(parts: List[Path], raw_limit: int,
                      email_limit: int) -> None:
    """Raise EmailError when a PDF part is still over ``raw_limit``:
    split_pdf leaves a single page larger than the limit as it is
    (issue #363)."""
    total = len(parts)
    for number, part in enumerate(parts, start=1):
        size = part.stat().st_size
        if size <= raw_limit:
            continue
        label = (f"PDF part {number} of {total}" if total > 1
                 else "PDF file")
        raise EmailError(
            f"{label} is {_format_mb(size)}, exceeding MeManga's "
            f"{_format_mb(raw_limit)} safe raw attachment limit. "
            f"Email attachments are base64 encoded, so the raw file must "
            f"stay below this limit to fit under the "
            f"{_format_mb(email_limit)} encoded email cap. "
            f"It can't be split any smaller because one page is larger "
            f"than this limit; nothing was sent."
        )


# What must match for an earlier attempt's accepted parts to count.
_PROGRESS_IDENTITY = ("total", "source_size", "source_mtime_ns",
                      "source_sha256", "recipient_sha256", "part_limit")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> Optional[str]:
    """SHA-256 of the file's bytes, or None when it can't be read."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as e:
        logger.warning("Could not read %s to identify it: %s", path.name, e)
        return None
    return digest.hexdigest()


def _split_progress(pdf_path: Path, total: int, kindle_email: str,
                    earlier: Optional[Mapping[str, Any]],
                    part_limit: int = MAX_ATTACHMENT_SIZE) -> Dict[str, Any]:
    """Delivery progress of ``pdf_path`` split into ``total`` parts of at
    most ``part_limit`` bytes for ``kindle_email``: the parts ``earlier``
    recorded as accepted when it describes the same file content, split
    and recipient, else none.

    The file is identified by its SHA-256 (plus size and mtime) and the
    recipient by the SHA-256 of the address, so the address itself is not
    stored. When the file can't be hashed, nothing counts as accepted.
    JSON-safe, so it can be kept in state."""
    stat = pdf_path.stat()
    current: Dict[str, Any] = {
        "total": total,
        "accepted": [],
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "source_sha256": _file_sha256(pdf_path),
        "recipient_sha256": _sha256(kindle_email.strip().encode("utf-8")),
        "part_limit": part_limit,
    }
    if not isinstance(earlier, Mapping):
        return current
    if (current["source_sha256"] is None
            or any(earlier.get(key) != current[key]
                   for key in _PROGRESS_IDENTITY)):
        logger.info("%s or its recipient changed since its earlier delivery "
                    "attempt; sending every part", pdf_path.name)
        return current
    accepted = earlier.get("accepted")
    if isinstance(accepted, list):
        current["accepted"] = sorted({
            n for n in accepted
            if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= total
        })
    return current


def _send_parts(
    pdf_path: Path,
    parts: List[Path],
    subject: str,
    earlier: Optional[Mapping[str, Any]],
    on_part_sent: Optional[Callable[[int, int], None]],
    *,
    kindle_email: str,
    sender_email: str,
    smtp_server: str,
    smtp_port: int,
    app_password: str,
    timeout: Optional[float],
    part_limit: int = MAX_ATTACHMENT_SIZE,
    smtp_tls: Optional[str] = None,
) -> None:
    """Send the parts of a split PDF not yet accepted, over one session."""
    total = len(parts)
    progress = _split_progress(pdf_path, total, kindle_email, earlier,
                               part_limit)
    accepted = progress["accepted"]
    pending = [n for n in range(1, total + 1) if n not in accepted]
    if accepted:
        logger.info("Not sending parts %s again: the mail server already "
                    "accepted them", ", ".join(str(n) for n in accepted))
    if not pending:
        return

    # The part being sent; None between a part's acceptance and the next.
    failed: Optional[int] = pending[0]
    try:
        with smtp_session(sender_email, smtp_server, smtp_port, app_password,
                          timeout=timeout, smtp_tls=smtp_tls) as server:
            for number in pending:
                failed = number
                part_path = parts[number - 1]
                try:
                    msg = _kindle_message(part_path, kindle_email,
                                          sender_email,
                                          f"{subject}.{str(number).zfill(2)}")
                except OSError as e:
                    # Not a connection problem, which smtp_session would
                    # report it as.
                    raise EmailError(
                        f"Could not read {part_path.name}: {e}") from e
                server.send_message(msg)
                failed = None
                accepted.append(number)
                logger.info("Part %d/%d accepted by the mail server",
                            number, total)
                if on_part_sent is not None:
                    on_part_sent(number, total)
    except Exception as e:
        if failed is None:
            # Raised by on_part_sent, not by sending.
            raise
        detail = str(e) if isinstance(e, EmailError) else f"Failed to send email: {e}"
        progress["accepted"] = sorted(accepted)
        raise EmailPartError(failed, total, progress, detail) from e


def _remove_split_parts(pdf_path: Path, parts: List[Path]) -> None:
    """Remove the temp folder split_pdf wrote ``parts`` to, if any. The
    original file and its folder are never touched."""
    folders = {part.parent for part in parts if part != pdf_path}
    for folder in folders:
        if folder == pdf_path.parent or not folder.name.startswith(SPLIT_DIR_PREFIX):
            continue
        try:
            shutil.rmtree(folder)
        except OSError as e:
            logger.warning("Could not remove split PDF parts in %s: %s",
                           folder, e)


def _kindle_message(pdf_path: Path, kindle_email: str, sender_email: str,
                    subject: str) -> EmailMessage:
    """The email carrying ``pdf_path`` (PDF or EPUB) as its attachment."""
    # Detect MIME type based on extension
    suffix = pdf_path.suffix.lower()
    mime_types = {
        '.epub': ('application', 'epub+zip'),
    }
    mime_main, mime_sub = mime_types.get(suffix, ('application', 'pdf'))

    with open(pdf_path, "rb") as f:
        data = f.read()
    return _attachment_message(data, pdf_path.name, mime_main, mime_sub,
                               kindle_email, sender_email, subject)


def _attachment_message(data: bytes, filename: str, mime_main: str,
                        mime_sub: str, kindle_email: str, sender_email: str,
                        subject: str) -> EmailMessage:
    """The email carrying ``data`` as the attachment ``filename``: a
    multipart/mixed message with one base64 part (email.policy.default)."""
    msg = EmailMessage()
    msg["From"] = sender_email
    msg["To"] = kindle_email
    msg["Subject"] = subject
    # add_attachment() sets MIME-Version on the child part; preserve it on
    # the outer message too.
    msg["MIME-Version"] = "1.0"
    msg.add_attachment(data, maintype=mime_main, subtype=mime_sub,
                       filename=filename)
    return msg


def _send_single_email(
    pdf_path: Path,
    kindle_email: str,
    sender_email: str,
    smtp_server: str,
    smtp_port: int,
    app_password: str,
    subject: str,
    timeout: Optional[float] = None,
    smtp_tls: Optional[str] = None,
) -> bool:
    """Send a single file (PDF or EPUB) via email."""
    msg = _kindle_message(pdf_path, kindle_email, sender_email, subject)
    
    # Send
    try:
        with smtp_session(sender_email, smtp_server, smtp_port, app_password,
                          timeout=timeout, smtp_tls=smtp_tls) as server:
            server.send_message(msg)
        return True
    except EmailError:
        raise
    except Exception as e:
        raise EmailError(f"Failed to send email: {e}") from e


def smtp_timeout(value=None) -> float:
    """The SMTP timeout to use: ``value`` when it is a number of seconds
    above 0 and at most MAX_SMTP_TIMEOUT, else DEFAULT_SMTP_TIMEOUT
    (unset or hand-edited config)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_SMTP_TIMEOUT
    # Compare without converting to float: YAML allows integers too large
    # for one (math.isfinite would raise OverflowError). NaN fails the
    # comparison and infinities are out of range.
    if not 0 < value <= MAX_SMTP_TIMEOUT:
        return DEFAULT_SMTP_TIMEOUT
    return value


def _port_number(port) -> Optional[int]:
    try:
        return int(port)
    except (TypeError, ValueError):
        return None


def smtp_tls_mode(value=None, port=None) -> str:
    """How to secure a connection to ``port``: "starttls" or "implicit".

    ``value`` is email.smtp_tls. "auto" or unset picks implicit TLS on
    port 465 (RFC 8314) and STARTTLS on any other port. Raises EmailError
    for anything outside SMTP_TLS_MODES rather than guessing, so a typo
    never changes how the password is protected.
    """
    mode = DEFAULT_SMTP_TLS if value is None else value
    if isinstance(mode, str):
        mode = mode.strip().lower()
    if mode not in SMTP_TLS_MODES:
        raise EmailError(
            f"Invalid email.smtp_tls {value!r}: expected one of "
            + ", ".join(SMTP_TLS_MODES))
    if mode == "auto":
        return ("implicit" if _port_number(port) == IMPLICIT_TLS_PORT
                else "starttls")
    return mode


def _with_tls_hint(message: str, mode: str, port) -> str:
    """``message``, plus a hint when the connection failed on a port that
    normally uses the other TLS mode (the usual cause of a hang on 465)."""
    port = _port_number(port)
    if mode == "starttls" and port == IMPLICIT_TLS_PORT:
        hint = (f"Port {port} normally uses implicit TLS, but "
                f"email.smtp_tls is starttls; set it to auto or implicit.")
    elif mode == "implicit" and port in STARTTLS_PORTS:
        hint = (f"Port {port} normally uses STARTTLS, but "
                f"email.smtp_tls is implicit; set it to auto or starttls.")
    else:
        return message
    return f"{message.rstrip('.')}. {hint}"


def _tls_context() -> ssl.SSLContext:
    """The TLS settings of every SMTP connection: certificate and host
    name checked, and at least TLS 1.2 (RFC 8314). The default context
    may leave the floor to the platform, which can allow older versions;
    a stricter platform floor is kept."""
    context = ssl.create_default_context()
    if context.minimum_version < ssl.TLSVersion.TLSv1_2:
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _caused_by_timeout(error: BaseException) -> bool:
    # smtplib turns a socket timeout while reading or sending into
    # SMTPServerDisconnected, keeping the TimeoutError only as context.
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, TimeoutError):
            return True
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return False


def _decode_reply(text) -> str:
    if isinstance(text, bytes):
        return text.decode("utf-8", "replace")
    return text or ""


def _refused_recipients(error: BaseException) -> Optional[dict]:
    """``{address: (code, reply)}`` when every recipient was refused.
    SMTPRecipientsRefused keeps the codes there, not in ``smtp_code``."""
    if not isinstance(error, smtplib.SMTPRecipientsRefused):
        return None
    return {address: (code, _decode_reply(reply))
            for address, (code, reply) in error.recipients.items()}


def _smtp_code(error: BaseException) -> Optional[int]:
    refused = _refused_recipients(error)
    if refused:
        # Delivery has a single recipient, the Kindle address.
        return next(iter(refused.values()))[0]
    return getattr(error, "smtp_code", None)


def _smtp_reply(error: BaseException) -> str:
    refused = _refused_recipients(error)
    if refused:
        # Replies only; the addresses stay in EmailProviderError.recipients.
        return "; ".join(f"{code} {reply}".strip()
                         for code, reply in refused.values())
    code = getattr(error, "smtp_code", None)
    text = _decode_reply(getattr(error, "smtp_error", None))
    if code is not None and text:
        return f"{code} {text}"
    return str(error) or type(error).__name__


def _smtp_error(error: BaseException, server: str, port, timeout: float,
                password: str, mode: str = "starttls") -> EmailError:
    """Map an smtplib/socket failure to the matching EmailError. ``mode``
    is the TLS mode used (see smtp_tls_mode)."""
    detail = _smtp_reply(error)
    if password:
        detail = detail.replace(password, "****")
    where = f"{server}:{port}"
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return EmailAuthError(
            f"SMTP authentication failed. Check email/password. "
            f"Server replied: {detail}")
    if _caused_by_timeout(error):
        return EmailTimeoutError(_with_tls_hint(
            f"SMTP server {where} did not respond within {timeout:g} seconds",
            mode, port))
    # SMTPException subclasses OSError, so only the socket-level errors
    # and the two smtplib connection errors count as connection failures;
    # any other SMTPException is a server reply.
    if (isinstance(error, (smtplib.SMTPConnectError,
                           smtplib.SMTPServerDisconnected))
            or not isinstance(error, smtplib.SMTPException)):
        return EmailConnectionError(_with_tls_hint(
            f"Connection to SMTP server {where} failed: {detail}",
            mode, port))
    return EmailProviderError(f"SMTP error from {where}: {detail}",
                              _smtp_code(error), _refused_recipients(error))


def _close_smtp(smtp, polite: bool) -> None:
    """End the session without raising. QUIT only on a working connection;
    it is bounded by the socket timeout."""
    if polite:
        try:
            smtp.quit()
            return
        except (smtplib.SMTPException, OSError):
            pass
    try:
        smtp.close()
    except OSError:
        pass


@contextmanager
def smtp_session(
    sender_email: str,
    smtp_server: str,
    smtp_port: int,
    app_password: str,
    timeout: Optional[float] = None,
    smtp_tls: Optional[str] = None,
) -> Iterator[smtplib.SMTP]:
    """Connect over TLS (certificate and host name checked) and log in;
    yield the logged-in connection.

    Issue #366: ``smtp_tls`` (email.smtp_tls, see smtp_tls_mode) picks
    implicit TLS from the first byte (SMTP_SSL, port 465) or a plain
    connection upgraded with STARTTLS before login (port 587). A server
    that does not offer STARTTLS is an error, never a cleartext login.

    Issue #361: shared by delivery, the Settings test and ``doctor``.
    Every socket operation waits at most ``timeout`` seconds. smtplib
    and socket failures, inside the block too, become EmailAuthError,
    EmailConnectionError, EmailTimeoutError or EmailProviderError, with
    the original exception chained. A failed QUIT after the block
    succeeded is ignored: the server already accepted the message.
    """
    timeout = smtp_timeout(timeout)
    mode = smtp_tls_mode(smtp_tls, smtp_port)
    register_secret(app_password)
    smtp = None
    polite = False
    try:
        if mode == "implicit":
            smtp = smtplib.SMTP_SSL(smtp_server, int(smtp_port),
                                    timeout=timeout, context=_tls_context())
        else:
            smtp = smtplib.SMTP(smtp_server, int(smtp_port), timeout=timeout)
            smtp.starttls(context=_tls_context())
        smtp.login(sender_email, app_password)
        yield smtp
        polite = True
    except (smtplib.SMTPException, OSError) as e:
        error = _smtp_error(e, smtp_server, smtp_port, timeout, app_password,
                            mode)
        # The server answered, so the connection still works.
        polite = isinstance(error, (EmailAuthError, EmailProviderError))
        raise error from e
    finally:
        if smtp is not None:
            _close_smtp(smtp, polite)


def smtp_login(
    sender_email: str,
    smtp_server: str,
    smtp_port: int,
    app_password: str,
    timeout: Optional[float] = None,
    smtp_tls: Optional[str] = None,
) -> None:
    """Log in the way delivery does, then log out. Raises an EmailError
    subclass on failure."""
    with smtp_session(sender_email, smtp_server, smtp_port, app_password,
                      timeout=timeout, smtp_tls=smtp_tls):
        pass


def check_email_config(
    sender_email: str,
    smtp_server: str,
    smtp_port: int,
    app_password: str,
    timeout: Optional[float] = None,
    smtp_tls: Optional[str] = None,
) -> bool:
    """
    Check that the sender can log in to the SMTP server. Connection
    check only: nothing is sent, so the Kindle address and Amazon's
    approved sender list are not tested (see send_test_document).
    
    Returns:
        True if connection successful
    """
    try:
        smtp_login(sender_email, smtp_server, smtp_port, app_password,
                   timeout=timeout, smtp_tls=smtp_tls)
        return True
    except Exception:
        return False


def test_email_config(
    sender_email: str,
    smtp_server: str,
    smtp_port: int,
    app_password: str,
    timeout: Optional[float] = None,
) -> bool:
    """Deprecated: use check_email_config."""
    warnings.warn(
        "test_email_config is deprecated; use check_email_config",
        DeprecationWarning,
        stacklevel=2,
    )
    return check_email_config(sender_email, smtp_server, smtp_port,
                              app_password, timeout=timeout)


# Not a test: keep pytest from collecting it when a test module imports it.
test_email_config.__test__ = False


# Issue #365: a real delivery test. Logging in proves neither the Kindle
# address nor that Amazon accepts mail from the sender, so the test sends
# a tiny PDF the same way delivery sends chapters.
TEST_DOCUMENT_NAME = "MeManga-test.pdf"
TEST_DOCUMENT_SUBJECT = "MeManga test document"
TEST_DELIVERY_NOTE = (
    "The mail server accepted the test PDF. That does not prove it reached "
    "your Kindle: Amazon delivers it only if the sender address is on your "
    "Approved Personal Document E-mail List. In a few minutes, look for "
    f"\"{TEST_DOCUMENT_SUBJECT}\" in your Kindle library or on Amazon's "
    "Manage Your Content and Devices page. If Amazon rejects it, it usually "
    "emails the sender address."
)


def _pdf_text(text: str) -> str:
    """``text`` as a PDF literal string (Latin-1 safe, special characters
    escaped)."""
    text = text.encode("latin-1", "replace").decode("latin-1")
    for char in ("\\", "(", ")"):
        text = text.replace(char, "\\" + char)
    return f"({text})"


def build_test_pdf(stamp: str) -> bytes:
    """A minimal valid one-page PDF identifying a MeManga test sent at
    ``stamp``. It uses only the standard Helvetica font, so it embeds
    nothing."""
    lines = [
        (24, TEST_DOCUMENT_SUBJECT),
        (12, f"Sent {stamp}"),
        (12, "If you can read this on your Kindle, email delivery works."),
    ]
    ops = ["BT", "72 720 Td"]
    for size, line in lines:
        ops += [f"/F1 {size} Tf", f"{_pdf_text(line)} Tj", f"0 -{size * 2} Td"]
    ops.append("ET")

    pdf = pikepdf.new()
    try:
        page = pdf.add_blank_page(page_size=(612, 792)).obj
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(
            F1=pikepdf.Dictionary(
                Type=pikepdf.Name.Font,
                Subtype=pikepdf.Name.Type1,
                BaseFont=pikepdf.Name.Helvetica,
                Encoding=pikepdf.Name.WinAnsiEncoding,
            )))
        page.Contents = pdf.make_stream("\n".join(ops).encode("latin-1"))
        pdf.docinfo["/Title"] = f"{TEST_DOCUMENT_SUBJECT} {stamp}"
        buffer = io.BytesIO()
        pdf.save(buffer)
    finally:
        pdf.close()
    return buffer.getvalue()


def send_test_document(
    kindle_email: str,
    sender_email: str,
    smtp_server: str,
    smtp_port: int,
    app_password: str,
    timeout: Optional[float] = None,
    now: Optional[datetime] = None,
    smtp_tls: Optional[str] = None,
) -> str:
    """Email a tiny test PDF to ``kindle_email`` over the same SMTP
    session as delivery (TLS per ``smtp_tls``, login, bounded by
    ``timeout``).

    Returns the subject sent once the mail server accepted the message.
    Acceptance is not proof that Amazon delivered it (TEST_DELIVERY_NOTE).

    Raises:
        EmailError: a setting is missing; or an EmailError subclass from
            smtp_session when connecting, logging in or sending fails
            (the password never appears in the message).
    """
    kindle_email = (kindle_email or "").strip()
    sender_email = (sender_email or "").strip()
    missing = [label for label, value in (
        ("Kindle email", kindle_email), ("sender email", sender_email),
        ("SMTP server", (smtp_server or "").strip()),
        ("app password", app_password),
    ) if not value]
    if missing:
        raise EmailError("Missing " + ", ".join(missing))
    register_secret(app_password)

    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    subject = f"{TEST_DOCUMENT_SUBJECT} {stamp}"
    msg = _attachment_message(build_test_pdf(stamp), TEST_DOCUMENT_NAME,
                              "application", "pdf", kindle_email,
                              sender_email, subject)
    with smtp_session(sender_email, smtp_server.strip(), smtp_port,
                      app_password, timeout=timeout,
                      smtp_tls=smtp_tls) as server:
        server.send_message(msg)
    logger.info("Test document accepted by the mail server")
    return subject
