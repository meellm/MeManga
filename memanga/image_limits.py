"""
Pixel limit for decoding page images (issue #386).

Page images come from websites and from chapter files, so they are
untrusted: a small file can declare a huge canvas (a "decompression
bomb") and exhaust memory when decoded. Every decode of a page image,
by the downloader and by the reader, checks the size the image header
declares against one limit before any pixels are decoded, and refuses
the image with ImageTooLargeError when it is over.

The limit is MAX_PAGE_PIXELS = 2,048 x 65,535 pixels (about 134
megapixels). Webtoon pages are tall strips, rarely wider than 2,000
pixels, and 65,535 pixels is the tallest a JPEG can be (the side limit
of the JPEG format; WebP stops at 16,383), so a strip as wide as any
source serves reaches the tallest JPEG and still fits. Decoded at 4
bytes per pixel, as Pillow and Qt hold an RGBA page, the largest
accepted page takes 512 MiB, which bounds what one decode can claim.
Pillow's own default (about 89 megapixels, a warning only; an error at
twice that) would refuse legitimate strips and gives no clear message,
and Qt's default 256 MiB allocation limit (about 67 megapixels at 4
bytes per pixel) is lower still.

Importing this module also sets Pillow's process-wide limit to the
same value, so an image opened through Pillow anywhere else (a library,
a script) is held to it too: Pillow warns above the limit and refuses
an image above twice it.
"""

from PIL import Image

MAX_PAGE_PIXELS = 2048 * 65535

Image.MAX_IMAGE_PIXELS = MAX_PAGE_PIXELS


class ImageTooLargeError(ValueError):
    """An image declares more pixels than MAX_PAGE_PIXELS allows.

    Raised before any pixels are decoded. Not worth retrying: the same
    image is refused again."""


def exceeds_pixel_limit(width: int, height: int) -> bool:
    """True when a *width* x *height* image is over MAX_PAGE_PIXELS."""
    return width * height > MAX_PAGE_PIXELS


def check_image_size(width: int, height: int) -> None:
    """Raise ImageTooLargeError when a *width* x *height* image is over
    MAX_PAGE_PIXELS. A size of zero (unknown) passes."""
    if exceeds_pixel_limit(width, height):
        raise ImageTooLargeError(
            f"image is {width} x {height} pixels "
            f"({width * height / 1e6:.1f} megapixels), over the "
            f"{MAX_PAGE_PIXELS / 1e6:.1f}-megapixel limit for page images"
        )


def _declared_size(fp):
    """(width, height) from the header of an image Pillow refused to open
    for its size, or None when it can't be read.

    Identifies the format the way Image.open() does, with Pillow's
    registered openers, but stops at the header: an opener reads only
    the size and mode, and no pixels are decoded."""
    own = isinstance(fp, (str, bytes)) or hasattr(fp, "__fspath__")
    try:
        fh = open(fp, "rb") if own else fp
    except OSError:
        return None
    try:
        Image.init()
        fh.seek(0)
        prefix = fh.read(16)
        for fmt in Image.ID:
            factory, accept = Image.OPEN[fmt]
            result = accept(prefix) if accept else True
            if not result or isinstance(result, str):
                continue
            try:
                fh.seek(0)
                img = factory(fh, None)
            except Exception:
                continue
            try:
                return img.size
            finally:
                img.close()
        return None
    except Exception:
        return None
    finally:
        if own:
            fh.close()


def open_image(fp):
    """Image.open() held to MAX_PAGE_PIXELS.

    Like Image.open(), only the header is read; the image is closed and
    ImageTooLargeError raised when it is over the limit, so no pixels
    are ever decoded for it."""
    try:
        img = Image.open(fp)
    except (Image.DecompressionBombError,
            Image.DecompressionBombWarning) as e:
        # Pillow refuses an image over twice the limit while opening;
        # its warning (over the limit) is raised too when warnings are
        # turned into errors. Its message gives its own threshold and no
        # dimensions, so the refusal is reported like any other.
        size = _declared_size(fp)
        if size is not None:
            try:
                check_image_size(*size)
            except ImageTooLargeError as refusal:
                raise refusal from e
        raise ImageTooLargeError(
            f"image is over the {MAX_PAGE_PIXELS / 1e6:.1f}-megapixel "
            f"limit for page images"
        ) from e
    try:
        check_image_size(*img.size)
    except ImageTooLargeError:
        img.close()
        raise
    return img
