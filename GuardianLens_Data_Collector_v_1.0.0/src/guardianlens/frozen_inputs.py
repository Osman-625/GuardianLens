"""Versioned collection backups and offline verification, isolated from the live app.

Source SQLite connections are URI mode=ro. No source files are written, removed,
renamed, re-encoded or linked. A complete manifest is published only after a
stable-source check. Incomplete attempts are retained for inspection, never deleted.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from typing import Callable
import uuid

import yaml

from .frozen_input_checks import (
    CONTENT_FIELDS, analyze, dump_csv, dump_json, dump_jsonl, reconcile_handoff,
    write_review_page,
)

ASSET_ROOTS = ("data/private/screenshots", "data/private/staging", "data/private/replay_batches", "data/images", "data/temporary", "data/reports", "logs")
SOURCE_ROOTS = ("src", "extension", "config", "scripts", "tests", "docs")
SOURCE_FILES = (
    "main.py", "run.bat", "setup.bat", "requirements.txt", "environment.yml",
    "pyproject.toml", "package.json", "package-lock.json", "README.md",
    "MANIFEST.sha256", ".env.example", ".gitignore", "VERSION", "AGENTS.md", "CLAUDE.md",
)
SECRET_FILES = (".env", "data/private/local_token.txt", "data/private/ai_provider_override.txt")


class SnapshotError(RuntimeError):
    """The attempt is retained but cannot be presented as a consistent freeze."""


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_only_database(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def database_copy(source: Path, destination: Path | None = None) -> sqlite3.Connection:
    """SQLite online backup preserves WAL commits without checkpointing the source."""
    if destination is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb"):
            pass
    reader = read_only_database(source)
    output = sqlite3.connect(destination if destination is not None else ":memory:")
    try:
        deadline = time.monotonic() + 60
        def checkpoint(_status: int, _remaining: int, _total: int) -> None:
            if time.monotonic() > deadline:
                raise SnapshotError("Database backup could not finish within 60 seconds; writer may be busy")
        reader.backup(output, pages=256, progress=checkpoint, sleep=0.05)
        output.row_factory = sqlite3.Row
        output.execute("PRAGMA query_only=ON")
        return output
    except BaseException:
        output.close()
        raise
    finally:
        reader.close()


def fingerprint(con: sqlite3.Connection) -> str:
    """Digest schema and all table values; independent of SQLite page layout."""
    digest = hashlib.sha256()
    schema = [tuple(row) for row in con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]
    digest.update(json.dumps(schema, ensure_ascii=False).encode())
    digest.update(str(con.execute("PRAGMA user_version").fetchone()[0]).encode())
    for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        table = row[0].replace('"', '""')
        digest.update(table.encode())
        columns = list(con.execute(f'PRAGMA table_info("{table}")'))
        order = [c[1] for c in sorted(columns, key=lambda c: c[5]) if c[5]]
        ordering = ",".join('"' + key.replace('"', '""') + '"' for key in order) or "rowid"
        for item in con.execute(f'SELECT * FROM "{table}" ORDER BY {ordering}'):
            values = [{"blob_hex": v.hex()} if isinstance(v, bytes) else v for v in item]
            digest.update(json.dumps(values, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def health(con: sqlite3.Connection) -> dict:
    result = {
        "quick_check": [r[0] for r in con.execute("PRAGMA quick_check")],
        "integrity_check": [r[0] for r in con.execute("PRAGMA integrity_check")],
        "foreign_key_violations": [list(r) for r in con.execute("PRAGMA foreign_key_check")],
        "schema_version": con.execute("PRAGMA user_version").fetchone()[0],
    }
    if result["quick_check"] != ["ok"] or result["integrity_check"] != ["ok"] or result["foreign_key_violations"]:
        raise SnapshotError("Frozen database failed integrity checks")
    return result


def _plain_path(path: Path, root: Path) -> None:
    if not path.resolve().is_relative_to(root.resolve()):
        raise SnapshotError("Source path escapes expected root")
    current = path
    while current != root:
        if current == current.parent:
            raise SnapshotError("Path is not lexically contained in the expected root")
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise SnapshotError("Linked paths are not supported in a frozen package")
        current = current.parent


def inventory(root: Path, folders: tuple[str, ...], singles: tuple[str, ...] = ()) -> dict:
    result = {}
    for name in folders:
        folder = root / name
        if not folder.exists():
            continue
        _plain_path(folder, root)
        def walk_error(error: OSError) -> None:
            raise error
        for base, dirs, files in os.walk(folder, followlinks=False, onerror=walk_error):
            dirs[:] = sorted(d for d in dirs if d not in {"__pycache__", ".pytest_cache", "node_modules", ".git"})
            for directory in dirs:
                _plain_path(Path(base) / directory, root)
            for file in sorted(files):
                path = Path(base) / file
                _plain_path(path, root)
                stat = path.stat()
                result[path.relative_to(root).as_posix()] = {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    for name in singles:
        path = root / name
        if path.is_file():
            _plain_path(path, root)
            stat = path.stat()
            result[name] = {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return dict(sorted(result.items()))


def observe(root: Path) -> dict:
    con = database_copy(root / "data/collector.sqlite3")
    try:
        active = {}
        for table in ("capture_batches", "processing_runs", "seller_retry_batches", "attention_agent_runs"):
            counts = con.execute(f"SELECT status,count(*) FROM {table} WHERE status IN ('running','paused','stopping') GROUP BY status").fetchall()
            if counts:
                active[table] = dict(counts)
        in_progress = dict(con.execute("SELECT status,count(*) FROM listings WHERE status IN ('processing','ai_extracted','validating','under_review') GROUP BY status"))
        if in_progress:
            active["listings"] = in_progress
        assets = inventory(root, ASSET_ROOTS)
        return {
            "observed_at": timestamp(), "database_fingerprint": fingerprint(con),
            "listing_status_counts": dict(con.execute("SELECT status,count(*) FROM listings GROUP BY status")),
            "active_work": active, "asset_inventory_fingerprint": hashlib.sha256(json.dumps(assets, sort_keys=True).encode()).hexdigest(),
            "asset_files": len(assets), "asset_bytes": sum(item["bytes"] for item in assets.values()),
            "process_visibility": "Process existence does not prove activity; no process is stopped or signalled.",
        }
    finally:
        con.close()


def stable_observations(first: dict, second: dict) -> bool:
    return not (first["active_work"] or second["active_work"]) and all(
        first[key] == second[key] for key in ("database_fingerprint", "asset_inventory_fingerprint")
    )


def copy_inventory(root: Path, destination: Path, entries: dict, progress: Callable[[str], None]) -> dict:
    copied = {}
    for index, (relative, expected) in enumerate(entries.items(), 1):
        source, target = root / relative, destination / relative
        _plain_path(source, root)
        before = source.stat()
        if (before.st_size, before.st_mtime_ns) != (expected["bytes"], expected["mtime_ns"]):
            raise SnapshotError("Source asset changed before copying: " + relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with source.open("rb") as reader, target.open("xb") as writer:
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(chunk)
                digest.update(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise SnapshotError("Source asset changed while copying: " + relative)
        copied[relative] = {**expected, "sha256": digest.hexdigest()}
        if index % 500 == 0:
            progress(f"Copied without modifying originals: {index}/{len(entries)} files")
    return copied


def _dictionary(con: sqlite3.Connection) -> dict:
    schema = {}
    for entry in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        table = entry[0]
        schema[table] = {"columns": [dict(row) for row in con.execute(f'PRAGMA table_info("{table}")')],
                         "foreign_keys": [dict(row) for row in con.execute(f'PRAGMA foreign_key_list("{table}")')]}
    return {
        "database": schema,
        "candidate_membership": "Exactly listings.status='approved' at the frozen database snapshot; join images through listing_id.",
        "identifiers": "Original listing_id and image_id are preserved. No relabelling or replacement IDs.",
        "private_candidates": "listings.jsonl preserves every approved source column and value; images.jsonl preserves every associated image row.",
        "public_index": "IDs, platform, numeric listing/seller fields and mechanical-check metadata only. Free text, URLs, images, private paths and credentials are withheld, not rewritten.",
        "nullable": "SQLite PRAGMA notnull=0 means nullable; TEXT PRIMARY KEY does not by itself imply explicit NOT NULL.",
        "csv": "UTF-8 BOM; NULL becomes empty cell. Formula-shaped text gets a leading apostrophe in CSV only. JSONL/database retain original values.",
        "strict_collection_gate_pass": "Offline current field/image/duplicate checks; not proof of semantic accuracy or fraud/non-fraud.",
        "semantic_correctness": "Always unverified in this automated report; evidence-based human verification remains outstanding.",
        "sources": {field: ("AI extraction and possible review/maintenance edits; examine ai_extractions, review_actions and status_history") for field in CONTENT_FIELDS},
        "image_hashes": "SHA-256 of stored image bytes and 64-bit difference hash (not SSCD).",
        "field_meanings": {
            "listing_id": "Original internal UUID; join key for listing evidence and histories.",
            "marketplace_listing_id": "Marketplace identifier, unique together with platform when nonempty; private provenance.",
            "image_id": "Original image UUID; each stored image row belongs to one listing_id.",
            "title": "Collected/possibly human-corrected listing title; private text.",
            "description": "Collected/possibly human-corrected listing body; multilingual private text.",
            "category": "Collector category from the frozen config/categories.yaml vocabulary.",
            "condition": "Extracted or corrected condition text; not independently certified.",
            "price": "Recorded numeric listing asking price in currency units; zero may be ambiguous.",
            "currency": "Recorded currency code, normally MYR; no currency conversion performed.",
            "location_state": "Recorded state text, source value preserved even when absent or inconsistent.",
            "location_city": "Optional recorded city text; location details remain private.",
            "account_age_days": "Recorded seller-account age in days at capture; estimates/rounding need source evidence.",
            "seller_rating": "Recorded seller rating, expected 0..5; marketplace app ratings can contaminate it.",
            "review_count": "Recorded seller-review count, nonnegative integer; confirm seller rather than app/product scope.",
            "active_listing_count": "Recorded seller inventory count; may represent only captured visible cards.",
            "language": "Recorded language indication; no independent language classification performed.",
            "status": "Collection lifecycle state; approved is candidate membership, never a fraud label.",
            "storage_path": "Original project-relative path to exact stored product bytes in the restored project.",
            "file_size_bytes": "Stored image byte length; checked against copied bytes.",
            "width / height": "Stored pixel dimensions; checked by decoding the copied image.",
            "source_position": "Capture image ordering value, retained exactly; gaps may reflect suppression.",
            "is_primary": "Original primary-image marker; exactly one per listing expected.",
            "screenshot_path / seller_screenshot_path / staging_text_path": "Private source evidence references; file availability reported separately; old references can remain after retention cleanup.",
            "structured_output": "Original serialized AI attempt output, not ground truth and never re-extracted here.",
            "previous_data / updated_data": "Original serialized human-review correction history; no field replacement by this tool.",
            "capture_batch_id / csv_row / original_csv_filename": "Replay/import provenance, backed by capture_batch_items and capture_batch_attempts.",
            "timestamps": "Original SQLite TEXT timestamp values preserved; no timezone normalization or fabricated dates.",
        },
        "public_numeric_withholding": "Non-numeric source values in numeric index columns are withheld as empty CSV cells, never repaired. Original values and type findings remain private.",
    }


def _write_report(path: Path, summary: dict) -> None:
    counts = summary["counts"]
    text = f"""# Frozen GuardianLens collection verification

Snapshot: {summary['snapshot_id']}
Database captured: {summary['database_captured_at']}

This package is separate from the live collector. No annotations, fraud labels,
training eligibility or dataset splits have been created. Existing collection
values and approval outcomes are preserved, including questionable values.

## Results

- Listings: {counts['listings']}; approved candidate records: {counts['approved_annotation_test']}.
- Product images: {counts['images']}; approved image associations: {summary['approved_images']}.
- Approved records passing strict mechanical checks: {summary['approved_strict_gate_pass']}.
- Approved records failing strict mechanical checks: {summary['approved_strict_gate_blocked']}.
- Approved records with recorded automatic approval: {summary['approved_automatic_approval_recorded']}.
- Product-image integrity failures: {summary['all_image_integrity_failures']}.
- Semantically verified records: 0. Mechanical validation cannot establish factual accuracy.
- Handoff matches frozen data: {summary['handoff_current']}.

## What to inspect

Open `../private/review/index.html` for a private, read-only record browser.
It shows every approved record, findings, copied product images, original AI
attempts and collection history. It never contacts or writes to the live app.
`../private/reports/approved_record_verification.csv` is the per-record checklist;
the JSONL version preserves nested findings without spreadsheet conversion.
`../private/reports/all_record_verification.jsonl` covers the entire collection.
`../private/reports/image_verification.jsonl` covers every registered image.

## Outstanding evidence and quality work

Missing private evidence, automatic approvals, strict-gate exceptions, prior AI
disagreement, manual NULL-to-zero edits and possible marketplace-app seller
statistics require human source verification. Do not infer that an absent AI
value was absent on the marketplace. Do not infer that an earlier AI value is
correct solely because it was recorded. Absent files were not recreated.

Duplicate-image suppression may have removed later listing associations.
Similarity and duplicate warnings are not fraud evidence. Seller inventory
counts may cover only captured visible items. Numeric completeness is not
correctness. All-record PII detector findings are heuristic, not confirmed leaks.

## Privacy and portability

Only the metadata index, aggregate reports and dictionary are in `public/`.
Title/description, location, URLs, page titles, image pixels, private evidence,
raw AI output and review notes remain in `private/`. The public index is not a
publication-approved ML dataset. Credentials are separately in `private/secrets/`.
The full backup is sensitive. Do not distribute the entire package publicly.

The package is self-contained: product images and remaining private evidence are
copied under `private/backup/project/`, retaining original relative paths. Source
and uncommitted working files are in `private/workspace/`. A full separate restore
check is recorded in `../private/reports/restore_verification.json`.

The final manifest is the completion marker. Verification is checksum-based;
this is an immutable-by-convention release, not WORM storage. Never overwrite
this generation; use a new timestamped generation for subsequent approvals.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)


def verify_snapshot(snapshot: Path) -> dict:
    snapshot = snapshot.resolve()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("state") != "complete":
        raise SnapshotError("Snapshot does not have a complete manifest")
    failures = []
    for relative, entry in manifest["files"].items():
        path = snapshot / relative
        _plain_path(path, snapshot)
        if not path.is_file() or path.stat().st_size != entry["bytes"] or sha_file(path) != entry["sha256"]:
            failures.append(relative)
    actual = {p.relative_to(snapshot).as_posix() for p in snapshot.rglob("*") if p.is_file()}
    unexpected = sorted(actual - set(manifest["files"]) - {"manifest.json"})
    con = read_only_database(snapshot / "private/backup/project/data/collector.sqlite3")
    try:
        database_health = health(con)
        database_matches = fingerprint(con) == manifest["database_fingerprint"]
    finally:
        con.close()
    if failures or unexpected or not database_matches:
        raise SnapshotError(f"Snapshot verification failed: {len(failures)} damaged/missing files, {len(unexpected)} unexpected files; database match={database_matches}")
    return {"verified_at": timestamp(), "files_verified": len(manifest["files"]), "database": database_health, "pass": True}


def _restore_project(project: Path, destination: Path, expected_fingerprint: str, progress: Callable[[str], None]) -> dict:
    destination.mkdir(parents=True, exist_ok=False)
    entries = inventory(project, ("data", "logs"))
    copy_inventory(project, destination, entries, progress)
    failures = [relative for relative in entries if sha_file(project / relative) != sha_file(destination / relative)]
    con = read_only_database(destination / "data/collector.sqlite3")
    try:
        database_health = health(con)
        same = fingerprint(con) == expected_fingerprint
        counts = {r[0]: con.execute(f'SELECT COUNT(*) FROM "{r[0]}"').fetchone()[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    finally:
        con.close()
    if failures or not same:
        raise SnapshotError("Isolated restore failed byte/database equality checks")
    return {"pass": True, "restored_at": timestamp(), "restore_path": str(destination),
            "files_verified": len(entries), "database_fingerprint": expected_fingerprint,
            "database": database_health, "table_counts": counts,
            "application_started": False, "secrets_installed": False,
            "meaning": "Exact collection database and available runtime assets restored; credentials and app startup deliberately excluded."}


def freeze(root: Path, *, observation_seconds: float = 5, progress: Callable[[str], None] = print) -> Path:
    root = root.resolve()
    first = observe(root)
    progress("First writer/asset observation complete")
    time.sleep(observation_seconds)
    second = observe(root)
    if not stable_observations(first, second):
        raise SnapshotError("Active or changing collection detected. No source process was stopped. Try again after coordinating an idle window.")
    generation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:10]
    snapshot = root / "data/backups/frozen_inputs" / generation
    _plain_path(snapshot.parent, root)
    snapshot.mkdir(parents=True, exist_ok=False)
    con = None
    try:
        project = snapshot / "private/backup/project"
        entries = inventory(root, ASSET_ROOTS)
        source_entries = inventory(root, SOURCE_ROOTS, SOURCE_FILES)
        secret_entries = inventory(root, (), SECRET_FILES)
        required_bytes = sum(i["bytes"] for i in entries.values()) * 3 + 512 * 1024 * 1024
        if shutil.disk_usage(snapshot).free < required_bytes:
            raise SnapshotError("Insufficient free space for backup, verification and isolated restore")
        con = database_copy(root / "data/collector.sqlite3", project / "data/collector.sqlite3")
        captured_at = timestamp()
        source_fingerprint = fingerprint(con)
        if source_fingerprint != second["database_fingerprint"]:
            raise SnapshotError("Database changed between observation and backup")
        database_health = health(con)
        progress("Consistent SQLite backup captured; copying private evidence and original image bytes")
        copied = copy_inventory(root, project, entries, progress)
        copied_source = copy_inventory(root, snapshot / "private/workspace", source_entries, progress)
        copied_secrets = copy_inventory(root, snapshot / "private/secrets", secret_entries, progress)
        # The handoff is advisory and may refresh independently of collection data.
        handoff_entries = inventory(root, ("data/exports/annotation_dataset",))
        handoff_stable = True
        try:
            copy_inventory(root, snapshot / "private/handoff_source", handoff_entries, progress)
            handoff_stable = handoff_entries == inventory(root, ("data/exports/annotation_dataset",))
        except (OSError, SnapshotError):
            handoff_stable = False
        handoff = snapshot / "private/handoff_source/data/exports/annotation_dataset"
        progress("Checking source stability before releasing it from the backup observation window")
        final_observation = observe(root)
        if not stable_observations(second, final_observation):
            raise SnapshotError("Collection changed during asset copy; attempt retained without a complete manifest")
        if entries != inventory(root, ASSET_ROOTS):
            raise SnapshotError("Asset inventory changed during freeze")
        # Hash again: size/mtime alone cannot establish content equality.
        for copied_group in (copied, copied_source, copied_secrets):
            for relative, info in copied_group.items():
                if sha_file(root / relative) != info["sha256"]:
                    raise SnapshotError("Source content changed during freeze: " + relative)
        if source_entries != inventory(root, SOURCE_ROOTS, SOURCE_FILES) or secret_entries != inventory(root, (), SECRET_FILES):
            raise SnapshotError("Source/configuration inventory changed during freeze")
        end = observe(root)
        if not stable_observations(final_observation, end):
            raise SnapshotError("Collection changed during final source verification")
        dump_json(snapshot / "private/reports/source_observations.json", [first, second, final_observation, end])
        dump_json(snapshot / "private/reports/source_file_inventory.json", {"assets": copied, "workspace": copied_source, "secrets": copied_secrets})
        categories = [item["name"] for item in yaml.safe_load((snapshot / "private/workspace/config/categories.yaml").read_text(encoding="utf-8"))["categories"]]
        progress("Source consistency verified. All remaining analysis uses the frozen copies")
        result = analyze(con, project, categories, progress)
        summary = result["summary"]
        summary.update({"snapshot_id": generation, "database_captured_at": captured_at,
                        "source_verified_through": end["observed_at"], "database_health": database_health})
        reconciliation = reconcile_handoff(handoff, result["rows"], summary["counts"], con) if handoff_stable else {"current": False, "reason": "handoff_changed_while_copying"}
        summary["handoff_current"] = reconciliation["current"]
        dump_json(snapshot / "private/reports/handoff_reconciliation.json", reconciliation)
        dump_jsonl(snapshot / "private/candidates/listings.jsonl", result["approved"])
        approved_ids = {row["listing_id"] for row in result["approved"]}
        dump_jsonl(snapshot / "private/candidates/images.jsonl", [dict(row) for row in con.execute(
            "SELECT i.* FROM images AS i JOIN listings AS l ON l.listing_id=i.listing_id "
            "WHERE l.status='approved' ORDER BY i.listing_id,i.source_position,i.image_id"
        )])
        for name, rows in [("all_record_verification", result["checks"]), ("approved_record_verification", result["approved_checks"]), ("image_verification", result["image_checks"])]:
            dump_jsonl(snapshot / f"private/reports/{name}.jsonl", rows)
        dump_csv(snapshot / "private/reports/approved_record_verification.csv", result["approved_checks"], list(result["approved_checks"][0]) if result["approved_checks"] else ["listing_id"])
        dump_csv(snapshot / "public/field_completeness.csv", result["completeness"], list(result["completeness"][0]))
        # Public-facing index intentionally withholds all free-form source text,
        # URLs and pixels. Their original values remain in private candidates.
        public_fields = ["listing_id", "platform", "price", *CONTENT_FIELDS[8:12]]
        public_rows = [{field: (row.get(field) if field in {"listing_id", "platform"}
                               or isinstance(row.get(field), (int, float)) else None)
                        for field in public_fields} for row in result["approved"]]
        dump_csv(snapshot / "public/approved_index.csv", public_rows, public_fields)
        dump_json(snapshot / "public/data_dictionary.json", _dictionary(con))
        dump_json(snapshot / "public/summary.json", summary)
        write_review_page(snapshot / "private/review/index.html", result)
        _write_report(snapshot / "public/VERIFICATION_REPORT.md", summary)
        protocol = snapshot / "private/workspace/docs/ANNOTATION_PROTOCOL_DRAFT.md"
        if protocol.is_file():
            with (snapshot / "public/ANNOTATION_PROTOCOL_DRAFT.md").open("xb") as handle:
                handle.write(protocol.read_bytes())
        # No app imports, startup or secrets are required to demonstrate restoration.
        restore = root / "data/backups/restore_checks" / generation / "project"
        _plain_path(restore.parent, root)
        restored = _restore_project(project, restore, source_fingerprint, progress)
        dump_json(snapshot / "private/reports/restore_verification.json", restored)
        dump_json(restore.parent / "RESTORE_VERIFIED.json", restored)
        con.close()
        con = None
        files = {}
        for path in sorted(snapshot.rglob("*")):
            if path.is_file():
                files[path.relative_to(snapshot).as_posix()] = {"bytes": path.stat().st_size, "sha256": sha_file(path)}
        manifest = {"format_version": 1, "snapshot_id": generation, "state": "complete",
                    "completed_at": timestamp(), "database_captured_at": captured_at,
                    "source_verified_through": end["observed_at"], "database_fingerprint": source_fingerprint,
                    "source_open_mode": "SQLite URI mode=ro and query_only", "source_rows_changed": False,
                    "images_reencoded": False, "annotation_labels_created": False,
                    "public_release_approved": False, "counts": summary["counts"], "files": files}
        dump_json(snapshot / "manifest.json", manifest)
        return snapshot
    except BaseException as exc:
        # No cleanup/deletion: a failed attempt remains explicitly incomplete.
        dump_json(snapshot / "FAILED_ATTEMPT.json", {"state": "incomplete", "failed_at": timestamp(), "error_type": type(exc).__name__, "reason": str(exc)})
        raise
    finally:
        if con is not None:
            con.close()


def restore_snapshot(snapshot: Path, destination: Path, progress: Callable[[str], None] = print) -> dict:
    """Restore data to a brand-new isolated directory, never into any existing path."""
    snapshot, destination = snapshot.resolve(), destination.resolve()
    if destination.exists() or destination == snapshot or destination.is_relative_to(snapshot) or snapshot.is_relative_to(destination):
        raise SnapshotError("Restore destination must be new and separate from the frozen package")
    verify_snapshot(snapshot)
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    return _restore_project(snapshot / "private/backup/project", destination, manifest["database_fingerprint"], progress)
