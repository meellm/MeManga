"""
Email handler for MeManga - sends PDFs to Kindle

Automatically splits large PDFs that exceed Gmail's 25MB limit.
"""

import smtplib
import tempfile
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path
from typing import Optional, List
import pikepdf


class EmailError(Exception):
    """Base exception for email errors."""
    pass


# Gmail limit is 25MB, use 23MB to be safe (base64 encoding adds ~33% overhead)
MAX_ATTACHMENT_SIZE = 23 * 1024 * 1024  # 23MB


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
    
    # Check file type - only split PDFs, send EPUBs as-is
    is_epub = pdf_path.suffix.lower() == '.epub'
    
    if is_epub:
        # EPUB: send as-is (no splitting)
        parts = [pdf_path]
        is_split = False
    else:
        # PDF: check if needs splitting
        parts = split_pdf(pdf_path)
        is_split = len(parts) > 1
        
        if is_split:
            print(f"     📎 Split into {len(parts)} parts (exceeded 25MB limit)")
    
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
        )
    
    # Cleanup temp files if split
    if is_split:
        for part_path in parts:
            try:
                part_path.unlink()
                part_path.parent.rmdir()  # Remove temp dir if empty
            except:
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
) -> bool:
    """Send a single file (PDF or EPUB) via email."""
    # Create message
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = kindle_email
    msg["Subject"] = subject
    
    # Detect MIME type based on extension
    is_epub = pdf_path.suffix.lower() == '.epub'
    if is_epub:
        mime_main = "application"
        mime_sub = "epub+zip"
    else:
        mime_main = "application"
        mime_sub = "pdf"
    
    # Attach file
    with open(pdf_path, "rb") as f:
        part = MIMEBase(mime_main, mime_sub)
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f"attachment; filename={pdf_path.name}"
        )
        msg.attach(part)
    
    # Send
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, app_password)
            server.send_message(msg)
        return True
    
    except smtplib.SMTPAuthenticationError:
        raise EmailError("SMTP authentication failed. Check email/password.")
    except smtplib.SMTPException as e:
        raise EmailError(f"SMTP error: {e}")
    except Exception as e:
        raise EmailError(f"Failed to send email: {e}")


def test_email_config(
    sender_email: str,
    smtp_server: str,
    smtp_port: int,
    app_password: str,
) -> bool:
    """
    Test if email configuration works.
    
    Returns:
        True if connection successful
    """
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, app_password)
        return True
    except Exception:
        return False
