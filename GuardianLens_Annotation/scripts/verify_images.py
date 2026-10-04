"""Standalone image verification for this annotation workspace.

Operates ONLY on this workspace (no --source-repo, no source DB access) --
this is what makes the workspace portable/standalone once exported.
Re-checks every image against data/annotation_ready/images_manifest.json.
Fails loudly (non-zero exit) on any mismatch.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Pillow is required: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(2)

WORKSPACE = Path(__file__).resolve().parent.parent
READY = WORKSPACE / "data" / "annotation_ready"


def main() -> int:
    manifest_path = READY / "images_manifest.json"
    if not manifest_path.exists():
        print(f"FAIL: manifest not found at {manifest_path}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    listings_csv = READY / "listings.csv"
    with listings_csv.open(encoding="utf-8-sig", newline="") as f:
        listings = list(csv.DictReader(f))

    errors = []

    for rel_path, expected_sha in manifest.items():
        full_path = READY / rel_path
        if not full_path.exists():
            errors.append(f"MISSING FILE: {rel_path}")
            continue
        actual_sha = hashlib.sha256(full_path.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            errors.append(f"HASH MISMATCH: {rel_path} (expected {expected_sha}, got {actual_sha})")
            continue
        try:
            with Image.open(full_path) as im:
                im.verify()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"UNREADABLE: {rel_path} ({exc.__class__.__name__}: {exc})")

    for row in listings:
        listing_id = row["listing_id"]
        platform = row["platform"]
        folder = READY / "images" / platform / listing_id
        if not folder.exists() or not any(folder.iterdir()):
            errors.append(f"NO IMAGES: listing {listing_id} has no image folder or it is empty")

    if errors:
        print(f"FAILED: {len(errors)} problem(s) found", file=sys.stderr)
        for e in errors[:200]:
            print(f"  - {e}", file=sys.stderr)
        if len(errors) > 200:
            print(f"  ... and {len(errors) - 200} more", file=sys.stderr)
        return 1

    print(f"OK: {len(manifest)} images verified against manifest, {len(listings)} listings all have image folders.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
