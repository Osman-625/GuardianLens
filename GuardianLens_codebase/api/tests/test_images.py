# Tests for the photo checks: an oversized upload is refused without being read whole, a photo with
# too many pixels is a 422 (not a crash), and decoding runs in a worker thread so it cannot freeze
# the server for other requests.
from __future__ import annotations

import asyncio
import io
import threading

import pytest
from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

from api.errors import AppError
from api.services import images
from api.services.images import ImageLimits, validate_and_reencode_images

LIMITS = ImageLimits(max_images=10, max_bytes=5 * 1024 * 1024)


def png(size: tuple[int, int]) -> bytes:
    """Returns a flat PNG: tiny on disk however many pixels it has."""
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def upload(data: bytes | io.BytesIO) -> UploadFile:
    """Wraps bytes as an uploaded PNG."""
    file = io.BytesIO(data) if isinstance(data, bytes) else data
    return UploadFile(file, filename="a.png", headers=Headers({"content-type": "image/png"}))


def check(files: list[UploadFile], limits: ImageLimits = LIMITS) -> AppError:
    """Runs the photo checks on files that must be refused, and returns the error."""
    with pytest.raises(AppError) as caught:
        asyncio.run(validate_and_reencode_images(files, limits))
    return caught.value


def test_a_sideways_phone_photo_is_turned_upright() -> None:
    """A portrait photo stored 800 x 400 with Orientation 6 comes out 400 x 800, as it is shown."""
    sideways = Image.new("RGB", (800, 400), (200, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90 degrees clockwise to display"
    buffer = io.BytesIO()
    sideways.save(buffer, format="JPEG", exif=exif)
    file = UploadFile(
        io.BytesIO(buffer.getvalue()),
        filename="a.jpg",
        headers=Headers({"content-type": "image/jpeg"}),
    )

    [stored] = asyncio.run(validate_and_reencode_images([file], LIMITS))

    assert (stored.width_px, stored.height_px) == (400, 800)
    assert Image.open(io.BytesIO(stored.content)).size == (400, 800)


def test_a_photo_with_too_many_pixels_is_a_422(monkeypatch: pytest.MonkeyPatch) -> None:
    """A small file that decodes to a huge picture is refused before it is decoded."""
    monkeypatch.setattr(images, "MAX_PIXELS", 1_000_000)
    error = check([upload(png((1500, 1000)))])
    assert (error.status_code, error.code, error.field) == (
        422,
        "image_too_many_pixels",
        "images[0]",
    )


def test_pillows_decompression_bomb_error_is_a_422_not_a_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pillow refuses a far-too-large image at open time; that must reach the buyer as a 422."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    error = check([upload(png((64, 64)))])
    assert (error.status_code, error.code) == (422, "image_too_many_pixels")


def test_an_oversized_upload_is_read_only_one_byte_past_the_limit() -> None:
    """The size limit is enforced while reading, so a huge upload is never loaded whole."""
    requested: list[int] = []

    class Recording(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            requested.append(-1 if size is None else size)
            return super().read(size)

    error = check([upload(Recording(b"x" * 10_000))], ImageLimits(max_images=10, max_bytes=1000))
    assert (error.status_code, error.code) == (422, "image_too_large")
    assert requested == [1001]


def picture(fmt: str) -> bytes:
    """A tiny picture saved in the given Pillow format."""
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 30, 30)).save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "real", ["GIF", "BMP", "TIFF", "JPEG2000", "PPM", "PCX", "ICO", "TGA", "PNG"]
)
def test_a_file_must_really_be_the_type_it_claims(real: str) -> None:
    """A file labelled JPEG that is another format is refused, so only the three allowed decoders
    ever see an upload."""
    upload_as_jpeg = UploadFile(
        io.BytesIO(picture(real)), filename="a.jpg", headers=Headers({"content-type": "image/jpeg"})
    )
    error = check([upload_as_jpeg])
    assert (error.status_code, error.code, error.field) == (422, "invalid_image", "images[0]")


@pytest.mark.parametrize(
    ("mime", "fmt"), [("image/jpeg", "JPEG"), ("image/png", "PNG"), ("image/webp", "WEBP")]
)
def test_a_photo_of_the_claimed_type_still_passes(mime: str, fmt: str) -> None:
    """The three allowed types are read and saved again as themselves."""
    headers = Headers({"content-type": mime})
    file = UploadFile(io.BytesIO(picture(fmt)), filename="a", headers=headers)
    result = asyncio.run(validate_and_reencode_images([file], LIMITS))
    assert (result[0].mime, result[0].width_px) == (mime, 16)


def test_a_normal_photo_is_decoded_in_a_worker_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decoding is CPU work; on the event loop's own thread it would stall every other request."""
    loop_thread = threading.get_ident()
    threads: list[int] = []
    original = images._reencode

    def recording(raw: bytes, mime: str, index: int) -> tuple[bytes, int, int]:
        threads.append(threading.get_ident())
        return original(raw, mime, index)

    monkeypatch.setattr(images, "_reencode", recording)
    result = asyncio.run(validate_and_reencode_images([upload(png((64, 48)))], LIMITS))
    assert (result[0].width_px, result[0].height_px) == (64, 48)
    assert threads and threads[0] != loop_thread
