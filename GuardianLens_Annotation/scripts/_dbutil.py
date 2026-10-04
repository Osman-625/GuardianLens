"""Read-only helpers for querying the GuardianLens source collector database.

This module NEVER writes to the source repository. Every connection is opened
with SQLite's `mode=ro` URI flag, which makes the OS-level open itself
read-only (not just "we promise not to write") -- a stray UPDATE/INSERT will
raise `sqlite3.OperationalError: attempt to write a readonly database`
instead of silently succeeding.

The source repository path is always passed in explicitly (--source-repo /
a `source_repo` argument) rather than hardcoded, so this workspace does not
silently depend on the source tree during normal annotation -- only the
audit/export tooling needs it, once, and that need is explicit at the CLI.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB_RELATIVE_PATH = Path("data") / "collector.sqlite3"
IMAGES_RELATIVE_ROOT = Path("data") / "images"

# The 12 known categories from config/categories.yaml, copied here as a
# static literal (not parsed live) so this workspace has no PyYAML
# dependency and no live coupling to the source repo's config file.
KNOWN_CATEGORIES = [
    "Phones",
    "Laptops",
    "Tablets",
    "Audio",
    "Gaming",
    "Cameras",
    "Wearables",
    "Fashion",
    "Home Appliances",
    "Sports",
    "Collectibles",
    "Other",
]

KNOWN_PLATFORMS = ["carousell", "mudah"]


def db_path_for(source_repo: Path) -> Path:
    return source_repo / DB_RELATIVE_PATH


def images_root_for(source_repo: Path) -> Path:
    return source_repo / IMAGES_RELATIVE_ROOT


def open_source_db(source_repo: Path) -> sqlite3.Connection:
    """Open the source collector DB strictly read-only.

    Raises FileNotFoundError with a clear message if the DB file is missing,
    and lets sqlite3's own read-only enforcement raise on any write attempt.
    """
    db_path = db_path_for(source_repo)
    if not db_path.exists():
        raise FileNotFoundError(
            f"Source collector DB not found at {db_path}. "
            "Pass the correct --source-repo (the GuardianLens_Data_Collector "
            "checkout root, not this annotation workspace)."
        )
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_approved_listings(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM listings WHERE status = 'approved' ORDER BY listing_id"
    ).fetchall()


def fetch_images(conn: sqlite3.Connection, listing_id: str | None = None) -> list[sqlite3.Row]:
    if listing_id is None:
        return conn.execute(
            "SELECT * FROM images ORDER BY listing_id, source_position"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM images WHERE listing_id = ? ORDER BY source_position",
        (listing_id,),
    ).fetchall()


def _main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test the read-only DB connection.")
    parser.add_argument("--source-repo", required=True, type=Path)
    args = parser.parse_args()

    conn = open_source_db(args.source_repo)
    try:
        rows = fetch_approved_listings(conn)
        print(len(rows))
    finally:
        conn.close()


if __name__ == "__main__":
    _main()
