# Validation of the uploaded listing photos. Each photo is checked for type, size, and content,
# then decoded and saved again as a fresh file, so nothing the original carried (such as location
# or device metadata) is passed on.
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from api.errors import AppError
from api.models.domain import ImageInput

# The accepted upload types, and the Pillow format each is saved again as.
_ALLOWED = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}

# The most pixels one photo may have (about 6000 x 5000). A small file can still decode to a huge
# picture, and decoding needs about 3 bytes per pixel more than once over.
MAX_PIXELS = 30_000_000


@dataclass(frozen=True, slots=True)
class ImageLimits:
    """The upload limits: how many photos, and the largest size of each in bytes."""

    max_images: int
    max_bytes: int


def _too_many_pixels(field: str) -> AppError:
    """The 422 for a photo with more than MAX_PIXELS pixels."""
    return AppError(
        422,
        "image_too_many_pixels",
        f"Each image must be {MAX_PIXELS // 1_000_000} megapixels or smaller. Shrink it first.",
        field,
    )


def _reencode(raw: bytes, mime: str, index: int) -> tuple[bytes, int, int]:
    """Decodes one photo and saves a clean copy; returns the new bytes, width, and height.

    Plain CPU work, so the caller runs it in a worker thread. Raises a 422 naming `images[<n>]`
    when the pixel count is over MAX_PIXELS or the file cannot be read as an image.
    """
    field = f"images[{index}]"
    target = _ALLOWED[mime]
    try:
        # formats=[target]: without it Pillow decodes whatever the bytes really are (JPEG2000, TIFF,
        # GIF, ...), so a file labelled JPEG could reach decoders this API never meant to use.
        # Decoding the whole image rejects a corrupt file, and saving a new copy leaves the
        # original's metadata behind.
        with Image.open(io.BytesIO(raw), formats=[target]) as opened:
            width, height = opened.size
            if width * height > MAX_PIXELS:
                raise _too_many_pixels(field)
            opened.load()
            # Phones store a portrait photo sideways with an Orientation flag, and saving a new copy
            # drops the flag. Turn the pixels upright first, so the models see the photo as shown.
            upright = ImageOps.exif_transpose(opened)
            width, height = upright.size
            output = io.BytesIO()
            if target == "JPEG":
                clean = upright.convert("RGB")
                clean.save(output, format="JPEG", quality=92, optimize=True)
            elif target == "PNG":
                keeps_alpha = upright.mode in {"RGBA", "LA"}
                clean = upright.convert("RGBA" if keeps_alpha else "RGB")
                clean.save(output, format="PNG", optimize=True)
            else:
                clean = upright.convert("RGB")
                clean.save(output, format="WEBP", quality=92, method=4)
    except Image.DecompressionBombError as exc:
        raise _too_many_pixels(field) from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AppError(
            422, "invalid_image", "The file could not be read as a valid image.", field
        ) from exc
    return output.getvalue(), width, height


async def validate_and_reencode_images(
    uploads: list[UploadFile],
    limits: ImageLimits,
) -> list[ImageInput]:
    """Checks every uploaded photo and returns clean, re-encoded copies.

    Raises a 422 naming the photo (`images[<n>]`) when one has an unsupported type, is empty, is
    over the size or pixel limit, or cannot be read as an image, and a 422 on `images` when there
    are none or too many.
    """
    if not uploads:
        raise AppError(422, "images_required", "Add at least one listing image.", "images")
    if len(uploads) > limits.max_images:
        raise AppError(
            422,
            "too_many_images",
            f"Add no more than {limits.max_images} images.",
            "images",
        )

    results: list[ImageInput] = []
    for index, upload in enumerate(uploads):
        mime = (upload.content_type or "").lower()
        if mime not in _ALLOWED:
            raise AppError(
                422,
                "unsupported_image_type",
                "Use JPEG, PNG, or WebP images.",
                f"images[{index}]",
            )
        # Read one byte past the limit, so an oversized upload is refused without loading it whole.
        raw = await upload.read(limits.max_bytes + 1)
        if not raw:
            raise AppError(422, "empty_image", "The image file is empty.", f"images[{index}]")
        if len(raw) > limits.max_bytes:
            max_mb = limits.max_bytes // (1024 * 1024)
            raise AppError(
                422,
                "image_too_large",
                f"Each image must be {max_mb} MB or smaller.",
                f"images[{index}]",
            )

        # In a worker thread, so decoding a big photo does not freeze every other request.
        content, width, height = await run_in_threadpool(_reencode, raw, mime, index)
        results.append(
            ImageInput(
                filename=upload.filename or f"image-{index + 1}",
                mime=mime,
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
                width_px=width,
                height_px=height,
            )
        )
    return results
