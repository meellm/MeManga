"""Image conversion shared by the output format writers."""

import io
from pathlib import Path

from PIL import Image

from ...image_limits import open_image


def _image_to_jpeg_bytes(img_path: Path) -> tuple:
    """Convert any image to JPEG bytes suitable for EPUB/Kindle.

    Returns (jpeg_bytes, width, height). Raises ImageTooLargeError for
    an image over the page pixel limit.
    """
    img = open_image(img_path)
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
