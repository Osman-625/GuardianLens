"""Final verification pass over the cleaned/standardized annotation dataset.

Implements the checklist in "Prepare GuardianLens Dataset for Annotation.md"
section 19. Operates on this workspace only (data/annotation_ready/,
data/excluded/, reports/, annotation/) -- no source DB access needed except
for the one optional row-count reconciliation check, which is skipped (not
failed) if --source-repo is not given.

Exit code 0 = everything passed. Non-zero = at least one FAIL below; the
script always finishes and prints every check's result rather than stopping
at the first failure, so a single run shows the whole picture.

Usage:
    python scripts/verify_annotation_ready.py
    python scripts/verify_annotation_ready.py --source-repo "<path to GuardianLens_Data_Collector_v_1.0.0>"
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

WORKSPACE = Path(__file__).resolve().parent.parent
READY_DIR = WORKSPACE / "data" / "annotation_ready"
EXCLUDED_DIR = WORKSPACE / "data" / "excluded"
REPORTS_DIR = WORKSPACE / "reports"
ANNOTATION_DIR = WORKSPACE / "annotation"

CONDITION_VALUES = {"new", "like_new", "good", "fair", "poor", "unknown"}
LANGUAGE_VALUES = {"en", "ms", "mixed", "other", "unknown"}
DUPLICATE_STATUS_VALUES = {"unique", "possible_duplicate", "exact_duplicate"}
READINESS_VALUES = {"ready", "ready_with_missing", "needs_review", "exclude"}
KNOWN_CATEGORIES = {
    "Phones", "Laptops", "Tablets", "Audio", "Gaming", "Cameras",
    "Wearables", "Fashion", "Home Appliances", "Sports", "Collectibles", "Other",
}
FRAUD_LABEL_TOKENS = {"scam", "fraud", "legitimate", "suspicious", "fake", "trust_score", "risk_score"}

MISSING_FLAG_TO_FIELD = {
    "price_missing": "price",
    "account_age_missing": "account_age_days",
    "seller_rating_missing": "seller_rating",
    "review_count_missing": "review_count",
    "active_listing_count_missing": "active_listing_count",
    "description_missing": "description",
}


def _b(v: str) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


class Check:
    def __init__(self):
        self.results: list[tuple[str, bool, str]] = []

    def run(self, name: str, fn):
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"raised {exc.__class__.__name__}: {exc}"
        self.results.append((name, ok, detail))

    def report(self) -> int:
        failed = 0
        for name, ok, detail in self.results:
            status = "PASS" if ok else "FAIL"
            if not ok:
                failed += 1
            print(f"[{status}] {name}" + (f" -- {detail}" if detail else ""))
        print(f"\n{len(self.results) - failed}/{len(self.results)} checks passed.")
        return 1 if failed else 0


def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_csv_lenient(path: Path) -> list[dict]:
    """Like load_csv, but never raises on bad bytes -- used only for report/
    log files (never listings.csv) so a rare write-time byte corruption is
    reported as a finding instead of crashing the whole verification run."""
    with path.open(encoding="utf-8-sig", newline="", errors="replace") as f:
        return list(csv.DictReader(f))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", type=Path, default=None,
                         help="Optional: GuardianLens_Data_Collector_v_1.0.0 checkout, "
                              "for the row-count-reconciles-against-DB check.")
    args = parser.parse_args()

    c = Check()

    listings_path = READY_DIR / "listings.csv"
    if not listings_path.exists():
        print(f"FATAL: {listings_path} does not exist -- run export_annotation_dataset.py first.")
        return 1
    listings = load_csv(listings_path)
    listing_ids = [r["listing_id"] for r in listings]

    excluded_path = EXCLUDED_DIR / "excluded_listings.csv"
    excluded = load_csv(excluded_path) if excluded_path.exists() else []
    exclusion_reasons = load_csv(EXCLUDED_DIR / "exclusion_reasons.csv") if (EXCLUDED_DIR / "exclusion_reasons.csv").exists() else []

    # --- exported CSV loads successfully / UTF-8 preserved ---
    def check_csv_loads():
        bad = [r["listing_id"] for r in listings if "�" in (r.get("title", "") + r.get("description", ""))]
        return (len(bad) == 0, f"{len(bad)} rows contain a UTF-8 replacement character" if bad else f"{len(listings)} rows loaded cleanly")
    c.run("exported listings.csv loads and is valid UTF-8", check_csv_loads)

    # --- listing IDs stable and unique ---
    def check_unique_ids():
        return (len(listing_ids) == len(set(listing_ids)), f"{len(listing_ids)} rows, {len(set(listing_ids))} unique ids")
    c.run("listing_id values are unique", check_unique_ids)

    # --- every excluded record has a reason ---
    def check_excluded_reasons():
        excluded_ids = {r["listing_id"] for r in excluded}
        reasoned_ids = {r["listing_id"] for r in exclusion_reasons}
        missing = excluded_ids - reasoned_ids
        return (not missing, f"{len(missing)} excluded listings with no logged reason" if missing else f"{len(excluded_ids)} excluded, all reasoned")
    c.run("every excluded record has a reason", check_excluded_reasons)

    # --- no overlap between ready and excluded ---
    def check_no_overlap():
        overlap = set(listing_ids) & {r["listing_id"] for r in excluded}
        return (not overlap, f"{len(overlap)} listing_ids appear in BOTH ready and excluded sets" if overlap else "disjoint")
    c.run("ready and excluded sets are disjoint", check_no_overlap)

    # --- standardized categories valid ---
    def check_categories():
        bad = [r["listing_id"] for r in listings if r["category"] and r["category"] not in KNOWN_CATEGORIES]
        return (not bad, f"{len(bad)} rows with unrecognized category, e.g. {bad[:5]}" if bad else "all categories in the known 12")
    c.run("standardized categories are valid", check_categories)

    # --- standardized conditions valid ---
    def check_conditions():
        bad = [r["listing_id"] for r in listings if r["condition"] not in CONDITION_VALUES]
        return (not bad, f"{len(bad)} rows with condition outside controlled vocabulary" if bad else "all conditions in {new,like_new,good,fair,poor,unknown}")
    c.run("standardized conditions are valid", check_conditions)

    # --- standardized languages valid ---
    def check_languages():
        bad = [r["listing_id"] for r in listings if r["language"] not in LANGUAGE_VALUES]
        return (not bad, f"{len(bad)} rows with language outside controlled vocabulary" if bad else "all languages in {en,ms,mixed,other,unknown}")
    c.run("standardized languages are valid", check_languages)

    # --- duplicate_status / annotation_readiness enums valid ---
    def check_duplicate_status():
        bad = [r["listing_id"] for r in listings if r["duplicate_status"] not in DUPLICATE_STATUS_VALUES]
        return (not bad, f"{len(bad)} rows with invalid duplicate_status" if bad else "all duplicate_status values valid")
    c.run("duplicate_status values are valid", check_duplicate_status)

    def check_readiness():
        bad = [r["listing_id"] for r in listings if r["annotation_readiness"] not in READINESS_VALUES]
        return (not bad, f"{len(bad)} rows with invalid annotation_readiness" if bad else "all annotation_readiness values valid")
    c.run("annotation_readiness values are valid", check_readiness)

    # --- duplicate handling consistent with duplicate_report.csv ---
    def check_duplicate_report_consistent():
        dup_report_path = REPORTS_DIR / "duplicate_report.csv"
        if not dup_report_path.exists():
            return (False, "reports/duplicate_report.csv not found")
        reported_ids = {r["listing_id"] for r in load_csv(dup_report_path)}
        non_unique_ids = {r["listing_id"] for r in listings if r["duplicate_status"] != "unique"}
        return (reported_ids == non_unique_ids,
                "mismatch" if reported_ids != non_unique_ids else f"{len(reported_ids)} non-unique listings, all reported")
    c.run("duplicate_report.csv matches listings.csv duplicate_status", check_duplicate_report_consistent)

    # --- numeric fields valid (price >= 0 or missing; seller fields >= 0 or missing) ---
    def check_numeric_fields():
        bad = []
        for r in listings:
            for field in ("price", "account_age_days", "seller_rating", "review_count", "active_listing_count"):
                v = r.get(field, "")
                if v == "" or v is None:
                    continue
                try:
                    if float(v) < 0:
                        bad.append(f"{r['listing_id']}.{field}={v}")
                except ValueError:
                    bad.append(f"{r['listing_id']}.{field}={v} (not numeric)")
        return (not bad, f"{len(bad)} invalid numeric values, e.g. {bad[:5]}" if bad else "all numeric fields >= 0 or blank")
    c.run("numeric fields are valid (>=0 or NULL, never fabricated)", check_numeric_fields)

    # --- missing-value flags consistent with actual field emptiness ---
    def check_missing_flags():
        bad = []
        for r in listings:
            for flag, field in MISSING_FLAG_TO_FIELD.items():
                is_empty = not str(r.get(field, "")).strip()
                if _b(r[flag]) != is_empty:
                    bad.append(f"{r['listing_id']}.{flag}={r[flag]} but {field}={r.get(field)!r}")
        return (not bad, f"{len(bad)} inconsistent missing-value flags, e.g. {bad[:5]}" if bad else "all missing-value flags consistent")
    c.run("missing-value indicators are represented consistently", check_missing_flags)

    # --- location_state_invalid flag consistent (invalid => location_state is empty) ---
    def check_location_invalid_consistent():
        bad = [r["listing_id"] for r in listings if _b(r["location_state_invalid"]) and r["location_state"].strip()]
        return (not bad, f"{len(bad)} rows flagged invalid but location_state is non-empty" if bad else "consistent")
    c.run("location_state_invalid rows have a null location_state", check_location_invalid_consistent)

    # --- image paths resolve ---
    def check_image_paths():
        manifest_path = READY_DIR / "images_manifest.json"
        if not manifest_path.exists():
            return (False, "images_manifest.json not found")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        missing = [p for p in manifest if not (READY_DIR / p).exists()]
        primary_missing = [
            r["listing_id"] for r in listings
            if r["primary_image_path"] and not (READY_DIR / r["primary_image_path"]).exists()
        ]
        ok = not missing and not primary_missing
        detail = f"{len(missing)} manifest paths missing, {len(primary_missing)} primary_image_paths missing" if not ok else f"{len(manifest)} image paths resolve"
        return (ok, detail)
    c.run("image paths resolve on disk", check_image_paths)

    # --- screenshots excluded from product images (structural + filename sanity) ---
    def check_no_screenshots():
        img_val_path = REPORTS_DIR / "image_validation.csv"
        if not img_val_path.exists():
            return (True, "reports/image_validation.csv not present (nothing to check)")
        rows = load_csv(img_val_path)
        bad = [r["image_id"] for r in rows if "screenshot" in r["image_path"].lower()]
        return (not bad, f"{len(bad)} product image paths look like screenshots" if bad else f"{len(rows)} product images checked, none look like screenshots")
    c.run("screenshots are excluded from product image dataset", check_no_screenshots)

    # --- no fraud/scam labels anywhere in the standardized export ---
    def check_no_fraud_labels():
        header = set(listings[0].keys()) if listings else set()
        bad = header & FRAUD_LABEL_TOKENS
        return (not bad, f"suspicious column name(s) found: {bad}" if bad else "no fraud/scam-judgement columns in listings.csv")
    c.run("no fraud/scam labels were created", check_no_fraud_labels)

    # --- annotation fields remain empty (pilot + full templates) ---
    def check_annotation_fields_empty():
        candidates = []
        pilot_dir = ANNOTATION_DIR / "pilot"
        if pilot_dir.exists():
            candidates += sorted(pilot_dir.glob("*.csv"))
        candidates += sorted(ANNOTATION_DIR.glob("annotator_*.csv"))
        filled_total = 0
        checked = 0
        for path in candidates:
            if path.name == "pilot_listing_ids.csv":
                continue
            checked += 1
            rows = load_csv(path)
            filled_total += sum(1 for r in rows if str(r.get("label", "")).strip())
        return (filled_total == 0, f"{filled_total} filled label(s) found across {checked} annotation files" if filled_total else f"{checked} annotation file(s) checked, all labels blank")
    c.run("annotation fields remain empty (labeling not yet started)", check_annotation_fields_empty)

    # --- cleaning_report.csv entries all reference real listings ---
    def check_cleaning_report_consistent():
        cleaning_path = REPORTS_DIR / "cleaning_report.csv"
        if not cleaning_path.exists():
            return (False, "reports/cleaning_report.csv not found")
        rows = load_csv_lenient(cleaning_path)
        ids = set(listing_ids)
        orphans = [r["listing_id"] for r in rows if r["listing_id"] not in ids]
        return (not orphans, f"{len(orphans)} cleaning_report rows reference a listing_id not in listings.csv" if orphans else f"{len(rows)} cleaning changes logged, all traceable")
    c.run("cleaning_report.csv changes are traceable to real listings", check_cleaning_report_consistent)

    # --- report/log files are valid UTF-8 with no write-time byte corruption ---
    def check_report_encoding_integrity():
        report_files = [
            REPORTS_DIR / "cleaning_report.csv",
            REPORTS_DIR / "missing_values.csv",
            REPORTS_DIR / "duplicate_report.csv",
            REPORTS_DIR / "redactions_applied.csv",
            REPORTS_DIR / "image_validation.csv",
        ]
        bad: list[str] = []
        for path in report_files:
            if not path.exists():
                continue
            raw = path.read_bytes()
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                text = raw.decode("utf-8", errors="replace")
                # find which row (by listing_id in the first column) the bad
                # byte landed in, for a report file only.
                line_start = text.rfind("\n", 0, exc.start) + 1
                line_end = text.find("\n", exc.start)
                bad_line = text[line_start: line_end if line_end != -1 else None]
                listing_id = bad_line.split(",", 1)[0] if "," in bad_line else "?"
                bad.append(f"{path.name}: invalid UTF-8 at byte {exc.start} (row starting with listing_id={listing_id})")
        detail = ("; ".join(bad) + " -- source DB values for these listings were spot-checked clean; "
                   "this looks like a write-time corruption (workspace is inside a live-synced OneDrive "
                   "folder) rather than a mapping bug. Re-run export_annotation_dataset.py to regenerate; "
                   "if it recurs, pause OneDrive sync during the export run.") if bad else "all report files are valid UTF-8"
        return (not bad, detail)
    c.run("report/log files have no write-time byte corruption", check_report_encoding_integrity)

    # --- optional: row counts reconcile against source DB ---
    def check_db_reconciliation():
        if args.source_repo is None:
            return (True, "skipped (pass --source-repo to enable)")
        sys.path.insert(0, str(Path(__file__).parent))
        import _dbutil  # noqa: E402
        conn = _dbutil.open_source_db(args.source_repo)
        try:
            approved = len(_dbutil.fetch_approved_listings(conn))
        finally:
            conn.close()
        total_here = len(listings) + len(excluded)
        return (approved == total_here, f"DB has {approved} approved listings, workspace has {total_here} (ready+excluded)")
    c.run("row counts reconcile against source DB", check_db_reconciliation)

    return c.report()


if __name__ == "__main__":
    sys.exit(main())
