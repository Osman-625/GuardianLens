# Pins the loader for the visual reference cache (CLIP and SSCD embeddings of the approved training
# listings, saved by the training workspace as a compressed .npz file).
#
# Why this loader exists: the training workspace's own loader reads `z["clip"]`, `z["sscd"]` and
# `z["title"]` INSIDE its per-listing loop. A compressed npz decompresses a whole array every time a
# key is read, so with about two thousand listings that loader takes minutes, which would delay
# every API start-up. This loader reads each array once. These tests pin that it returns exactly
# what the training loader returns (same keys, shapes, float32 values) and that it stays fast as
# the number of listings grows.
from __future__ import annotations

import time
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from api.services.trained_visual import load_reference_cache  # noqa: E402


def write_cache(path: Path, listings: dict[str, int], dim: int = 512) -> None:
    """Writes a cache in the training workspace's format.

    The number of images varies per listing; every listing has one title row.
    """
    rng = np.random.default_rng(0)
    counts = list(listings.values())
    total = sum(counts)
    np.savez_compressed(
        path,
        ids=np.array(list(listings)),
        n=np.array(counts),
        clip=rng.normal(size=(total, dim)).astype(np.float16),
        sscd=rng.normal(size=(total, dim)).astype(np.float16),
        title=rng.normal(size=(len(listings), dim)).astype(np.float16),
    )


def test_returns_each_listings_embeddings_as_float32(tmp_path: Path) -> None:
    """Every listing gets its own float32 arrays, with the right shapes and the stored values."""
    path = tmp_path / "cache.npz"
    write_cache(path, {"a": 2, "b": 0, "c": 3})
    with np.load(path, allow_pickle=False) as raw:
        clip, sscd, title = raw["clip"], raw["sscd"], raw["title"]

    store = load_reference_cache(path)

    assert list(store) == ["a", "b", "c"]
    assert store["a"]["clip"].shape == (2, 512) and store["a"]["clip"].dtype == np.float32
    # A listing with no images keeps an empty array, which the visual features rely on.
    assert store["b"]["clip"].shape == (0, 512) and store["b"]["sscd"].shape == (0, 512)
    assert store["c"]["sscd"].shape == (3, 512)
    # Values equal the stored ones (offsets are cumulative over the listings' image counts).
    assert np.array_equal(store["a"]["clip"], clip[0:2].astype(np.float32))
    assert np.array_equal(store["c"]["clip"], clip[2:5].astype(np.float32))
    assert np.array_equal(store["c"]["sscd"], sscd[2:5].astype(np.float32))
    assert np.array_equal(store["b"]["title"], title[1].astype(np.float32))


def test_a_missing_file_gives_an_empty_cache(tmp_path: Path) -> None:
    """A cache file that does not exist loads as an empty mapping, not an error."""
    assert load_reference_cache(tmp_path / "nothing.npz") == {}


def test_loading_stays_fast_with_many_listings(tmp_path: Path) -> None:
    """Loading 800 listings stays well under a few seconds, so start-up does not stall."""
    # The training loader needs roughly 0.2 s per listing here; this one must take well under a
    # second for 800 listings. The bound is generous so a slow machine does not make it flaky.
    path = tmp_path / "cache.npz"
    write_cache(path, {f"id-{i}": 1 + i % 3 for i in range(800)})
    started = time.perf_counter()
    store = load_reference_cache(path)
    elapsed = time.perf_counter() - started
    assert len(store) == 800
    assert elapsed < 3.0, f"loading 800 listings took {elapsed:.1f} s"
