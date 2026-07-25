from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class BandBoundaries:
    low_max: int
    moderate_max: int

    def validate(self) -> None:
        if not 0 <= self.low_max < self.moderate_max <= 100:
            raise ValueError("Band boundaries must satisfy 0 <= low_max < moderate_max <= 100")


@dataclass(frozen=True, slots=True)
class BundleManifest:
    label: str
    dataset_version: str
    seed: int
    visual_version: str
    textual_version: str
    behavioural_version: str
    fusion_version: str
    calibrator_version: str
    explanation_templates_version: str
    category_baselines: dict[str, float]
    band_boundaries: BandBoundaries
    artifact_hashes: dict[str, str]
    dependency_lock_hash: str
    development_stub: bool = False

    @classmethod
    def load(cls, path: Path) -> "BundleManifest":
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        boundaries = BandBoundaries(**raw.pop("band_boundaries"))
        manifest = cls(band_boundaries=boundaries, **raw)
        manifest.validate()
        return manifest

    def validate(self) -> None:
        if not self.label.strip():
            raise ValueError("Bundle label is required")
        self.band_boundaries.validate()
        for name, digest in self.artifact_hashes.items():
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise ValueError(f"Invalid SHA-256 digest for {name}")
        if len(self.dependency_lock_hash) != 64:
            raise ValueError("dependency_lock_hash must be a SHA-256 digest")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
