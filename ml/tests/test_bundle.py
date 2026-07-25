from __future__ import annotations

from pathlib import Path

import pytest

from ml.src.guardianlens_ml.bundle import BandBoundaries, sha256_file


def test_band_boundaries_are_ordered() -> None:
    BandBoundaries(low_max=35, moderate_max=70).validate()
    with pytest.raises(ValueError):
        BandBoundaries(low_max=80, moderate_max=60).validate()


def test_sha256_file_is_stable(tmp_path: Path) -> None:
    target = tmp_path / "artifact.bin"
    target.write_bytes(b"guardianlens")
    assert sha256_file(target) == "2deda84d831a971fe248ff6f756b8146c5df561e67cd6813113b4dea0326c77c"
