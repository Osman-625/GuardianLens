from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from api.errors import AppError
from api.models.domain import ImageInput

_ALLOWED = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


@dataclass(frozen=True, slots=True)
class ImageLimits:
    max_images: int
    max_bytes: int


async def validate_and_reencode_images(
    uploads: list[UploadFile],
    limits: ImageLimits,
) -> list[ImageInput]:
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
        raw = await upload.read()
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

        try:
            with Image.open(io.BytesIO(raw)) as opened:
                opened.load()
                width, height = opened.size
                output = io.BytesIO()
                target = _ALLOWED[mime]
                if target == "JPEG":
                    clean = opened.convert("RGB")
                    clean.save(output, format="JPEG", quality=92, optimize=True)
                elif target == "PNG":
                    clean = (
                        opened.convert("RGBA")
                        if opened.mode in {"RGBA", "LA"}
                        else opened.convert("RGB")
                    )
                    clean.save(output, format="PNG", optimize=True)
                else:
                    clean = opened.convert("RGB")
                    clean.save(output, format="WEBP", quality=92, method=4)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise AppError(
                422,
                "invalid_image",
                "The file could not be read as a valid image.",
                f"images[{index}]",
            ) from exc

        content = output.getvalue()
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
