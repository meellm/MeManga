"""Image-folder writer (jpg, png, webp output formats)."""

from pathlib import Path
from typing import List

from PIL import Image

from ...image_limits import open_image
from ..errors import DownloaderError


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
        img = open_image(img_path)
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
