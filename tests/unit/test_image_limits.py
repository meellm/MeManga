"""
Pixel limit for page images (issue #386).

Covers the limit itself (tall webtoon strips fit, one pixel more does
not), the header-only refusal of open_image, the mapping of Pillow's
own decompression-bomb refusal, and Pillow's process-wide limit.
"""

import io
import warnings

import pytest
from PIL import Image

from memanga import image_limits
from memanga.image_limits import (MAX_PAGE_PIXELS, ImageTooLargeError,
                                  check_image_size, exceeds_pixel_limit,
                                  open_image)


def _png(size) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return buf.getvalue()


class TestLimit:
    def test_tallest_jpeg_strip_at_webtoon_width_fits(self):
        assert MAX_PAGE_PIXELS == 2048 * 65535
        assert not exceeds_pixel_limit(2048, 65535)
        check_image_size(2048, 65535)

    @pytest.mark.parametrize("size", [(2048, 65536), (2049, 65535),
                                      (MAX_PAGE_PIXELS + 1, 1)])
    def test_one_pixel_more_is_refused(self, size):
        assert exceeds_pixel_limit(*size)
        with pytest.raises(ImageTooLargeError) as exc:
            check_image_size(*size)
        message = str(exc.value)
        assert f"{size[0]} x {size[1]} pixels" in message
        assert "134.2-megapixel limit for page images" in message

    def test_unknown_size_passes(self):
        check_image_size(0, 0)

    def test_refusal_is_a_value_error(self):
        # Callers that already treat a bad image as ValueError keep doing so.
        assert issubclass(ImageTooLargeError, ValueError)

    def test_pillow_is_held_to_the_same_limit(self):
        assert Image.MAX_IMAGE_PIXELS == MAX_PAGE_PIXELS


class TestOpenImage:
    def test_image_within_limit_opens_as_before(self, monkeypatch):
        monkeypatch.setattr(image_limits, "MAX_PAGE_PIXELS", 40 * 60)
        with open_image(io.BytesIO(_png((40, 60)))) as img:
            img.load()
            assert img.size == (40, 60)

    def test_over_limit_image_is_refused_and_closed_before_decoding(
            self, monkeypatch):
        data = _png((40, 60))
        monkeypatch.setattr(image_limits, "MAX_PAGE_PIXELS", 40 * 60 - 1)
        closed = []
        real_close = Image.Image.close

        def spy(self):
            closed.append(self.size)
            real_close(self)
        monkeypatch.setattr(Image.Image, "close", spy)
        monkeypatch.setattr(Image.Image, "load", lambda self: pytest.fail(
            "over-limit image was decoded"))
        with pytest.raises(ImageTooLargeError):
            open_image(io.BytesIO(data))
        assert closed == [(40, 60)]

    def test_declared_bomb_is_refused_from_its_header(self, declared_png):
        # Far over: Pillow itself refuses it while opening.
        with pytest.raises(ImageTooLargeError) as exc:
            open_image(io.BytesIO(declared_png(100_000, 100_000)))
        assert isinstance(exc.value.__cause__, Image.DecompressionBombError)
        # Reported like any other refusal: its size and the page limit,
        # not Pillow's own threshold.
        assert str(exc.value) == (
            "image is 100000 x 100000 pixels (10000.0 megapixels), over the "
            "134.2-megapixel limit for page images")

    def test_declared_bomb_on_disk_is_reported_with_its_size(
            self, tmp_path, declared_png):
        path = tmp_path / "page.png"
        path.write_bytes(declared_png(100_000, 100_000))
        with pytest.raises(ImageTooLargeError,
                           match=r"100000 x 100000 pixels .* 134\.2-megapixel"):
            open_image(path)

    def test_declared_bomb_is_not_decoded_while_sizing_it(
            self, declared_png, monkeypatch):
        data = declared_png(100_000, 100_000)
        monkeypatch.setattr(Image.Image, "load", lambda self: pytest.fail(
            "over-limit image was decoded"))
        with pytest.raises(ImageTooLargeError, match="100000 x 100000"):
            open_image(io.BytesIO(data))

    def test_pillow_warning_turned_error_is_a_refusal(self, declared_png):
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with pytest.raises(ImageTooLargeError):
                open_image(io.BytesIO(declared_png(2048, 65536)))

    @pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
    def test_just_over_the_limit_is_refused(self, declared_png):
        with pytest.raises(ImageTooLargeError,
                           match="2048 x 65536 pixels"):
            open_image(io.BytesIO(declared_png(2048, 65536)))
