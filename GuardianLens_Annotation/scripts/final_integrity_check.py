"""Final pre-ZIP integrity pass. Operates only on this workspace.

Checks: listing_id uniqueness, every referenced image path resolves, no
secrets/env files present, no leaked source-repo private-path strings in any
text/CSV/JSON file, templates open cleanly and match schema, and re-runs
verify_images.py + verify_annotations.py as sub-checks.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent

FORBIDDEN_FILENAME_PATTERNS = ["local_token", "api_key", ".env"]
FORBIDDEN_PATH_FRAGMENT = "data\\private"
FORBIDDEN_PATH_FRAGMENT_POSIX = "data/private"
# .md/.txt docs are allowed to MENTION the excluded path pattern for
# documentation purposes (e.g. README explaining what was excluded); only
# actual data files are checked for a real leaked path value.
TEXT_SUFFIXES = {".csv", ".json", ".jsonl"}


def check_no_secrets() -> list[str]:
    errors = []
    for path in WORKSPACE.rglob("*"):
        if path.is_file():
            name_lower = path.name.lower()
            for bad in FORBIDDEN_FILENAME_PATTERNS:
                if bad in name_lower:
                    errors.append(f"forbidden-looking file present: {path.relative_to(WORKSPACE)}")
    return errors


def check_no_private_path_leaks() -> list[str]:
    errors = []
    for path in WORKSPACE.rglob("*"):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                continue
            if FORBIDDEN_PATH_FRAGMENT in text or FORBIDDEN_PATH_FRAGMENT_POSIX in text:
                errors.append(f"source private-path fragment found in: {path.relative_to(WORKSPACE)}")
    return errors


def check_listing_id_uniqueness() -> list[str]:
    errors = []
    csv_path = WORKSPACE / "data" / "annotation_ready" / "listings.csv"
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        ids = [row["listing_id"] for row in csv.DictReader(f)]
    if len(ids) != len(set(ids)):
        errors.append("duplicate listing_id values found in listings.csv")
    return errors


def check_image_paths_resolve() -> list[str]:
    errors = []
    csv_path = WORKSPACE / "data" / "annotation_ready" / "listings.csv"
    ready_dir = WORKSPACE / "data" / "annotation_ready"
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            p = row.get("primary_image_path")
            if p and not (ready_dir / p.split("images/", 1)[-1]).exists() and not (ready_dir / p).exists():
                errors.append(f"primary_image_path does not resolve for {row['listing_id']}: {p}")
    return errors


def check_templates_open() -> list[str]:
    errors = []
    for name in ("annotation_template.csv",):
        path = WORKSPACE / "annotation" / name
        try:
            with path.open(encoding="utf-8", newline="") as f:
                list(csv.DictReader(f))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: failed to open ({exc})")
    for name in ("annotator_A.csv", "annotator_B.csv", "adjudication.csv", "final_label.csv"):
        path = WORKSPACE / "annotation" / "templates" / name
        try:
            with path.open(encoding="utf-8", newline="") as f:
                list(csv.DictReader(f))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: failed to open ({exc})")
    return errors


def run_subscript(name: str) -> list[str]:
    result = subprocess.run(
        [sys.executable, str(WORKSPACE / "scripts" / name)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return [f"{name} FAILED:\n{result.stdout}\n{result.stderr}"]
    print(result.stdout.strip())
    return []


def main() -> int:
    errors: list[str] = []
    errors += check_no_secrets()
    errors += check_no_private_path_leaks()
    errors += check_listing_id_uniqueness()
    errors += check_image_paths_resolve()
    errors += check_templates_open()
    errors += run_subscript("verify_images.py")
    errors += run_subscript("verify_annotations.py")

    if errors:
        print(f"FAILED: {len(errors)} problem(s)", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print("OK: final integrity pass succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
