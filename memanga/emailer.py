"""
Email handler for MeManga - sends PDFs to Kindle

Automatically splits large PDFs that exceed Gmail's 25MB limit.
"""

import logging
import shutil
import smtplib
import ssl
import tempfile
from contextlib import contextmanager
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from email.utils import encode_rfc2231
from pathlib import Path
from typing import Iterator, Optional, List
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


# Issue #361: every SMTP socket operation (connect, greeting, TLS
# handshake, login, each chunk sent, QUIT) waits at most this long.
# It bounds a stalled server, not the total transfer time.
DEFAULT_SMTP_TIMEOUT = 60
# Upper bound of email.smtp_timeout (see CONFIG_KEYS in config.py).
MAX_SMTP_TIMEOUT = 600


# Gmail's attachment cap is 25MB after email encoding. Base64 adds roughly
# 33%, so keep raw files lower to stay under the encoded cap.
EMAIL_ATTACHMENT_LIMIT = 25 * 1024 * 1024
MAX_ATTACHMENT_SIZE = 18 * 1024 * 1024  # 18MB raw (~24MB after base64)


def _format_mb(size: int) -> str:
    """Format a byte count as MiB for user-facing messages."""
    return f"{size / (1024 * 1024):.1f}MB"


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
        temp_dir = Path(tempfile.mkdtemp(prefix="memanga_split_"))
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
) -> bool:
    """
    Send a PDF or EPUB to Kindle via email.
    
    Automatically splits large PDFs that exceed Gmail's limit.
    EPUB files are sent as-is (Kindle handles them natively).
    
    Args:
        pdf_path: Path to the PDF or EPUB file
        kindle_email: Kindle email address (xxx@kindle.com)
        sender_email: Sender email address (must be whitelisted in Amazon)
        smtp_server: SMTP server (e.g., smtp.gmail.com)
        smtp_port: SMTP port (usually 587 for TLS)
        app_password: App password for email account
        subject: Email subject (optional, defaults to filename)
        timeout: Seconds each SMTP operation may wait (defaults to
            DEFAULT_SMTP_TIMEOUT)
    
    Returns:
        True if sent successfully
    
    Raises:
        EmailError: If sending fails
    """
    if not pdf_path.exists():
        raise EmailError(f"File not found: {pdf_path}")
    
    if not kindle_email or not sender_email:
        raise EmailError("Email addresses not configured")
    
    if not app_password:
        raise EmailError("App password not configured")
    # Issue #226: never let the password reach a log line.
    register_secret(app_password)
    
    # Check file type - only split PDFs, send EPUBs/CBZs/ZIPs as-is
    suffix = pdf_path.suffix.lower()
    is_single_file = suffix in ('.epub', '.cbz', '.zip')

    if is_single_file:
        # EPUB/CBZ: check size (cannot split these formats)
        file_size = pdf_path.stat().st_size
        if file_size > MAX_ATTACHMENT_SIZE:
            fmt = suffix.lstrip('.').upper()
            raise EmailError(
                f"{fmt} file is {_format_mb(file_size)}, exceeding MeManga's "
                f"{_format_mb(MAX_ATTACHMENT_SIZE)} safe raw attachment limit. "
                f"Email attachments are base64 encoded, so the raw file must "
                f"stay below this limit to fit under the "
                f"{_format_mb(EMAIL_ATTACHMENT_LIMIT)} encoded email cap. "
                f"{fmt} files cannot be split. Use PDF format instead "
                f"(set in 'memanga config')."
            )
        parts = [pdf_path]
        is_split = False
    else:
        # PDF: check if needs splitting
        parts = split_pdf(pdf_path)
        is_split = len(parts) > 1
        
        if is_split:
            logger.info(
                "Split into %d parts (exceeded %s safe raw attachment limit; "
                "encoded email cap is %s)",
                len(parts), _format_mb(MAX_ATTACHMENT_SIZE),
                _format_mb(EMAIL_ATTACHMENT_LIMIT),
            )
    
    # Send each part
    for i, part_path in enumerate(parts):
        part_subject = subject or pdf_path.stem
        if is_split:
            part_subject = f"{part_subject}.{str(i+1).zfill(2)}"
        
        _send_single_email(
            pdf_path=part_path,
            kindle_email=kindle_email,
            sender_email=sender_email,
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            app_password=app_password,
            subject=part_subject,
            timeout=timeout,
        )
    
    # Cleanup temp files if split
    if is_split and parts:
        try:
            shutil.rmtree(parts[0].parent)
        except Exception:
            pass
    
    return True


def _send_single_email(
    pdf_path: Path,
    kindle_email: str,
    sender_email: str,
    smtp_server: str,
    smtp_port: int,
    app_password: str,
    subject: str,
    timeout: Optional[float] = None,
) -> bool:
    """Send a single file (PDF or EPUB) via email."""
    # Create message
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = kindle_email
    msg["Subject"] = subject
    
    # Detect MIME type based on extension
    suffix = pdf_path.suffix.lower()
    mime_types = {
        '.epub': ('application', 'epub+zip'),
        '.cbz': ('application', 'vnd.comicbook+zip'),
        '.zip': ('application', 'zip'),
    }
    mime_main, mime_sub = mime_types.get(suffix, ('application', 'pdf'))
    
    # Attach file
    with open(pdf_path, "rb") as f:
        part = MIMEBase(mime_main, mime_sub)
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=pdf_path.name,
        )
        msg.attach(part)
    
    # Send
    try:
        with smtp_session(sender_email, smtp_server, smtp_port, app_password,
                          timeout=timeout) as server:
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
                password: str) -> EmailError:
    """Map an smtplib/socket failure to the matching EmailError."""
    detail = _smtp_reply(error)
    if password:
        detail = detail.replace(password, "****")
    where = f"{server}:{port}"
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return EmailAuthError(
            f"SMTP authentication failed. Check email/password. "
            f"Server replied: {detail}")
    if _caused_by_timeout(error):
        return EmailTimeoutError(
            f"SMTP server {where} did not respond within {timeout:g} seconds")
    # SMTPException subclasses OSError, so only the socket-level errors
    # and the two smtplib connection errors count as connection failures;
    # any other SMTPException is a server reply.
    if (isinstance(error, (smtplib.SMTPConnectError,
                           smtplib.SMTPServerDisconnected))
            or not isinstance(error, smtplib.SMTPException)):
        return EmailConnectionError(
            f"Connection to SMTP server {where} failed: {detail}")
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
) -> Iterator[smtplib.SMTP]:
    """Connect, upgrade with STARTTLS (certificate and host name checked)
    and log in; yield the logged-in connection.

    Issue #361: shared by delivery, the Settings test and ``doctor``.
    Every socket operation waits at most ``timeout`` seconds. smtplib
    and socket failures, inside the block too, become EmailAuthError,
    EmailConnectionError, EmailTimeoutError or EmailProviderError, with
    the original exception chained. A failed QUIT after the block
    succeeded is ignored: the server already accepted the message.
    """
    timeout = smtp_timeout(timeout)
    register_secret(app_password)
    smtp = None
    polite = False
    try:
        smtp = smtplib.SMTP(smtp_server, int(smtp_port), timeout=timeout)
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(sender_email, app_password)
        yield smtp
        polite = True
    except (smtplib.SMTPException, OSError) as e:
        error = _smtp_error(e, smtp_server, smtp_port, timeout, app_password)
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
) -> None:
    """Log in the way delivery does, then log out. Raises an EmailError
    subclass on failure."""
    with smtp_session(sender_email, smtp_server, smtp_port, app_password,
                      timeout=timeout):
        pass


def test_email_config(
    sender_email: str,
    smtp_server: str,
    smtp_port: int,
    app_password: str,
    timeout: Optional[float] = None,
) -> bool:
    """
    Test if email configuration works.
    
    Returns:
        True if connection successful
    """
    try:
        smtp_login(sender_email, smtp_server, smtp_port, app_password,
                   timeout=timeout)
        return True
    except Exception:
        return False
