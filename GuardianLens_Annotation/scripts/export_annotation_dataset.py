"""Export the annotation-ready dataset from the source collector DB.

Reads reports/per_listing_validation.json (from validate_dataset.py) to
decide the annotation_ready / excluded split, then re-queries the source DB
(read-only) for full rows, applies copy-only redaction/normalization and
standardization, copies image files, and writes everything into data/.
Never writes to the source repository.

Standardization performed here (see ../../"Prepare GuardianLens Dataset for
Annotation.md" sections 4-16 for the spec this implements):

  - condition   -> controlled vocabulary (new/like_new/good/fair/poor/unknown),
                   original text preserved in condition_raw.
  - language    -> controlled vocabulary (en/ms/mixed/other/unknown),
                   original text preserved in language_raw.
  - location_state -> canonical Malaysian state/federal-territory spelling,
                   or one of the three project-accepted broad-region values
                   (West Malaysia / East Malaysia / Nationwide, see memory
                   8411 -- these are deliberate, not junk). Anything else
                   (shop names, malformed multi-state strings, non-Malaysia
                   places) is nulled out with location_state_invalid=True and
                   the original preserved in location_state_raw -- never
                   silently dropped.
  - missing-value indicator flags for the seller-behaviour fields, location,
    description and price (NULL means "unknown", never fabricated).
  - duplicate_status (unique / possible_duplicate) from the near-duplicate
    image and metadata-repost groups already computed by validate_dataset.py.
  - contains_redacted_pii / redacted_pii_count: the source collector's own
    pii.py always substitutes a single generic "[REDACTED]" token at capture
    time (pattern *type* is intentionally not persisted anywhere -- see
    memory 8815/8380/8683), so a per-type has_phone_number/has_email/
    has_bank_identifier breakdown is NOT honestly derivable post-hoc from
    stored data. This flag/count is the closest truthful signal available.
  - annotation_readiness (ready / ready_with_missing / needs_review) computed
    from the above. "exclude" is not assigned here -- that split already
    happened in validate_dataset.py before this script ever sees the row.

Every standardization decision that changes a value is logged to
reports/cleaning_report.csv (listing_id, field, old_value, new_value, reason,
cleaning_rule) so it stays fully traceable per spec section 18.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _dbutil  # noqa: E402
import _piiscan  # noqa: E402

EXPORT_FIELDS = [
    "listing_id", "platform", "marketplace_listing_id", "source_url",
    "category", "title", "description",
    "condition", "condition_raw",
    "price", "price_missing", "currency",
    "location_state", "location_state_raw", "location_state_invalid", "location_city",
    "location_missing",
    "language", "language_raw",
    "account_age_days", "account_age_missing",
    "seller_rating", "seller_rating_missing",
    "review_count", "review_count_missing",
    "active_listing_count", "active_listing_count_missing",
    "description_missing",
    "captured_at", "ai_provider", "ai_model", "ai_prompt_version",
    "image_count", "primary_image_path", "reused_image_indicator",
    "contains_redacted_pii", "redacted_pii_count",
    "duplicate_status",
    "annotation_readiness",
    "validation_status",
]

# Fields that existed in the pre-standardization export; excluded_listings.csv
# (which mirrors invalid/rejected rows straight from the DB, never cleaned)
# keeps using this simpler set.
EXCLUDED_EXPORT_FIELDS = [
    "listing_id", "platform", "marketplace_listing_id", "source_url",
    "category", "title", "description", "condition", "price", "currency",
    "location_state", "location_city", "language",
    "account_age_days", "seller_rating", "review_count", "active_listing_count",
    "captured_at", "ai_provider", "ai_model", "ai_prompt_version",
]

REDACT_TEXT_FIELDS = ["title", "description", "condition", "location_state", "location_city"]

# --- Section 8: condition standardization -----------------------------------

CONDITION_MAP = {
    "brand new": "new",
    "brand new with tags": "new",
    "new": "new",
    "like new": "like_new",
    "refurbished": "like_new",
    "lightly used": "good",
    "pre-owned (used)": "good",
    "pre owned (used)": "good",
    "used": "good",
    "second-hand (used)": "good",
    "second hand (used)": "good",
    "well used": "fair",
    "used - fair": "fair",
    "heavily used": "poor",
}


def normalize_condition(raw: str | None) -> tuple[str, bool]:
    """Returns (standardized_value, mapping_uncertain)."""
    if raw is None or not str(raw).strip():
        return "unknown", False
    key = re.sub(r"\s+", " ", str(raw).strip().lower()).replace("–", "-").replace("—", "-")
    if key in CONDITION_MAP:
        return CONDITION_MAP[key], False
    return "unknown", True  # non-empty but unrecognized wording -> needs human review


# --- Section 12: language standardization -----------------------------------

_EN_RE = re.compile(r"\ben\b|english", re.I)
_MS_RE = re.compile(r"\bms\b|malay|bahasa melayu", re.I)
_OTHER_RE = re.compile(r"chinese|mandarin|cantonese|\bzh\b|japanese|tamil|korean|thai", re.I)


def normalize_language(raw: str | None) -> tuple[str, bool]:
    """Returns (standardized_value, mapping_uncertain). Never translates text."""
    if raw is None or not str(raw).strip():
        return "unknown", False
    has_en = bool(_EN_RE.search(raw))
    has_ms = bool(_MS_RE.search(raw))
    has_other = bool(_OTHER_RE.search(raw))
    if has_en and has_ms:
        return "mixed", False
    if has_en and not has_other:
        return "en", False
    if has_ms and not has_other:
        return "ms", False
    if has_other:
        return "other", False
    return "unknown", True  # non-empty but unrecognized wording -> needs human review


# --- Section 10: location_state standardization -----------------------------

CANONICAL_STATES = {
    "selangor": "Selangor",
    "kuala lumpur": "Kuala Lumpur",
    "kl": "Kuala Lumpur",
    "johor": "Johor",
    "penang": "Penang",
    "pulau pinang": "Penang",
    "kedah": "Kedah",
    "perak": "Perak",
    "kelantan": "Kelantan",
    "sabah": "Sabah",
    "pahang": "Pahang",
    "melaka": "Melaka",
    "malacca": "Melaka",
    "negeri sembilan": "Negeri Sembilan",
    "sarawak": "Sarawak",
    "terengganu": "Terengganu",
    "putrajaya": "Putrajaya",
    "perlis": "Perlis",
    "labuan": "Labuan",
    "wp labuan": "Labuan",
}

# Deliberate, project-accepted broad-region values (see memory 8411) --
# these are NOT states but ARE legitimate seller-provided scope, so they are
# kept as-is rather than treated as invalid/junk.
ACCEPTED_REGIONS = {
    "west malaysia": "West Malaysia",
    "east malaysia": "East Malaysia",
    "nationwide": "Nationwide",
}


def normalize_location_state(raw: str | None) -> tuple[str | None, bool]:
    """Returns (standardized_value_or_None, invalid)."""
    if raw is None or not str(raw).strip():
        return None, False
    key = re.sub(r"\s+", " ", str(raw).strip().lower())
    if key in CANONICAL_STATES:
        return CANONICAL_STATES[key], False
    if key in ACCEPTED_REGIONS:
        return ACCEPTED_REGIONS[key], False
    return None, True  # shop name / malformed / non-Malaysia text leaked into this field


def normalize_currency(value):
    if value is None:
        return value
    v = str(value).strip().upper()
    return "MYR" if v == "RM" else value


def build_row(row, image_rows, reused_image_indicator: bool, validation_status: str,
              redaction_log: list, cleaning_log: list, duplicate_status: str):
    data = {k: row[k] for k in EXPORT_FIELDS if k in row.keys()}
    listing_id = row["listing_id"]

    for field in REDACT_TEXT_FIELDS:
        original = row[field]
        redacted, hit_labels = _piiscan.redact(original)
        if hit_labels:
            redaction_log.append({
                "listing_id": listing_id,
                "field": field,
                "pattern_types": ";".join(hit_labels),
            })
        data[field] = redacted

    original_currency = row["currency"]
    normalized_currency = normalize_currency(original_currency)
    if normalized_currency != original_currency:
        redaction_log.append({
            "listing_id": listing_id,
            "field": "currency",
            "pattern_types": f"currency_normalized:{original_currency}->{normalized_currency}",
        })
    data["currency"] = normalized_currency

    # --- condition ---
    condition_raw = data["condition"]
    condition_std, condition_uncertain = normalize_condition(condition_raw)
    if condition_std != (condition_raw or ""):
        cleaning_log.append({
            "listing_id": listing_id, "field": "condition",
            "old_value": condition_raw or "", "new_value": condition_std,
            "reason": "unrecognized wording, defaulted to unknown for review" if condition_uncertain
                      else "mapped marketplace text to controlled vocabulary",
            "cleaning_rule": "condition_vocabulary_v1",
        })
    data["condition_raw"] = condition_raw
    data["condition"] = condition_std

    # --- language ---
    language_raw = data["language"]
    language_std, language_uncertain = normalize_language(language_raw)
    if language_std != (language_raw or ""):
        cleaning_log.append({
            "listing_id": listing_id, "field": "language",
            "old_value": language_raw or "", "new_value": language_std,
            "reason": "unrecognized wording, defaulted to unknown for review" if language_uncertain
                      else "mapped free-text language description to controlled vocabulary",
            "cleaning_rule": "language_vocabulary_v1",
        })
    data["language_raw"] = language_raw
    data["language"] = language_std

    # --- location_state ---
    location_state_raw = data["location_state"]
    location_state_std, location_state_invalid = normalize_location_state(location_state_raw)
    if location_state_std != location_state_raw:
        cleaning_log.append({
            "listing_id": listing_id, "field": "location_state",
            "old_value": location_state_raw or "", "new_value": location_state_std or "",
            "reason": ("value is not a Malaysian state/federal territory or accepted region "
                       "(shop name, malformed text, or non-Malaysia place) -- nulled, flagged for review"
                       if location_state_invalid else "normalized spelling/alias to canonical state name"),
            "cleaning_rule": "location_state_vocabulary_v1",
        })
    data["location_state_raw"] = location_state_raw
    data["location_state"] = location_state_std
    data["location_state_invalid"] = location_state_invalid

    # --- missing-value indicators (Section 15) ---
    data["price_missing"] = data["price"] is None or data["price"] == ""
    data["account_age_missing"] = row["account_age_days"] is None
    data["seller_rating_missing"] = row["seller_rating"] is None
    data["review_count_missing"] = row["review_count"] is None
    data["active_listing_count_missing"] = row["active_listing_count"] is None
    data["description_missing"] = not (data["description"] or "").strip()
    data["location_missing"] = not (location_state_std or (data["location_city"] or "").strip())

    # --- PII residual signal (see module docstring for why this is not
    # broken down by phone/email/bank type) ---
    combined_text = f"{data['title'] or ''}\n{data['description'] or ''}"
    redacted_count = combined_text.count("[REDACTED]")
    data["contains_redacted_pii"] = redacted_count > 0
    data["redacted_pii_count"] = redacted_count

    data["image_count"] = len(image_rows)
    primary = next((r for r in image_rows if r["is_primary"]), None)
    if primary is None and image_rows:
        primary = sorted(image_rows, key=lambda r: r["source_position"] or 0)[0]
    data["primary_image_path"] = (
        f"images/{row['platform']}/{listing_id}/{Path(primary['storage_path']).name}"
        if primary else None
    )
    data["reused_image_indicator"] = reused_image_indicator
    data["duplicate_status"] = duplicate_status
    data["validation_status"] = validation_status

    # --- annotation_readiness (Section 16) ---
    needs_review = (
        duplicate_status == "possible_duplicate"
        or location_state_invalid
        or condition_uncertain
        or language_uncertain
    )
    any_missing = any([
        data["price_missing"], data["account_age_missing"], data["seller_rating_missing"],
        data["review_count_missing"], data["active_listing_count_missing"],
        data["description_missing"], data["location_missing"],
    ])
    if needs_review:
        data["annotation_readiness"] = "needs_review"
    elif any_missing:
        data["annotation_readiness"] = "ready_with_missing"
    else:
        data["annotation_readiness"] = "ready"

    return data


def run(source_repo: Path, workspace: Path) -> dict:
    reports_dir = workspace / "reports"
    per_listing = json.loads((reports_dir / "per_listing_validation.json").read_text(encoding="utf-8"))
    summary = json.loads((reports_dir / "dataset_validation_summary.json").read_text(encoding="utf-8"))
    cross_listing_ids = set(summary.get("near_duplicate_cross_listing_listing_ids", []))

    exact_dup_ids: set[str] = set()
    for key in ("duplicate_listing_ids", "duplicate_marketplace_ids",
                "duplicate_source_url_hashes", "duplicate_metadata_signatures"):
        for group in summary.get(key, []):
            ids = group if isinstance(group, list) else group.get("listing_ids", [])
            exact_dup_ids.update(ids)

    possible_dup_ids: set[str] = set(cross_listing_ids)
    for pair in summary.get("possible_repost_candidates", []):
        possible_dup_ids.update(pair)

    duplicate_group_map: dict[str, list[str]] = {}
    for group in summary.get("near_duplicate_cross_listing_groups", []):
        for lid in group.get("listing_ids", []):
            partners = [x for x in group.get("listing_ids", []) if x != lid]
            duplicate_group_map.setdefault(lid, []).extend(partners)
    for pair in summary.get("possible_repost_candidates", []):
        for lid in pair:
            partners = [x for x in pair if x != lid]
            duplicate_group_map.setdefault(lid, []).extend(partners)

    conn = _dbutil.open_source_db(source_repo)
    try:
        listings = {row["listing_id"]: row for row in _dbutil.fetch_approved_listings(conn)}
        all_images = _dbutil.fetch_images(conn)
    finally:
        conn.close()

    images_by_listing: dict[str, list] = {}
    for img in all_images:
        images_by_listing.setdefault(img["listing_id"], []).append(img)

    annotation_ready_dir = workspace / "data" / "annotation_ready"
    images_out_root = annotation_ready_dir / "images"
    excluded_dir = workspace / "data" / "excluded"
    reference_dir = workspace / "data" / "reference"
    for d in (annotation_ready_dir, images_out_root, excluded_dir, reference_dir):
        d.mkdir(parents=True, exist_ok=True)

    ready_rows = []
    excluded_rows = []
    exclusion_reasons = []
    redaction_log: list = []
    cleaning_log: list = []
    image_validation_rows: list = []
    images_manifest: dict[str, str] = {}

    total = len(per_listing)

    for index, (listing_id, verdict) in enumerate(per_listing.items(), 1):
        if index == 1 or index % 50 == 0 or index == total:
            print(
                f"[EXPORT] {index}/{total} listings processed "
                f"| {len(images_manifest)} images copied",
                flush=True,
            )

        row = listings[listing_id]
        image_rows = images_by_listing.get(listing_id, [])

        if verdict["status"] != "valid":
            excluded_rows.append({
                k: row[k]
                for k in EXCLUDED_EXPORT_FIELDS
                if k in row.keys()
            })

            for reason in verdict["reasons"] or ["unspecified"]:
                exclusion_reasons.append({
                    "listing_id": listing_id,
                    "reason_code": reason.split(":")[0],
                    "reason_detail": reason,
                })

            continue

        reused = listing_id in cross_listing_ids

        if listing_id in exact_dup_ids:
            dup_status = "exact_duplicate"
        elif listing_id in possible_dup_ids:
            dup_status = "possible_duplicate"
        else:
            dup_status = "unique"

        record = build_row(
            row,
            image_rows,
            reused,
            "valid",
            redaction_log,
            cleaning_log,
            dup_status,
        )

        ready_rows.append(record)

        dest_dir = images_out_root / row["platform"] / listing_id

        for img in image_rows:
            failed = img["image_id"] in verdict["image_ids_failed"]
            rel_path = ""

            if not failed:
                src_path = source_repo / img["storage_path"]

                dest_dir.mkdir(parents=True, exist_ok=True)

                dest_path = dest_dir / Path(img["storage_path"]).name

                dest_path.write_bytes(src_path.read_bytes())

                actual_sha = hashlib.sha256(
                    dest_path.read_bytes()
                ).hexdigest()

                if img["sha256"] and actual_sha != img["sha256"]:
                    raise RuntimeError(
                        f"Copy corruption detected for "
                        f"{img['image_id']} ({listing_id})"
                    )

                rel_path = str(
                    dest_path.relative_to(annotation_ready_dir)
                ).replace("\\", "/")

                images_manifest[rel_path] = actual_sha

            image_validation_rows.append({
                "listing_id": listing_id,
                "image_id": img["image_id"],
                "image_path": rel_path,
                "is_primary": bool(img["is_primary"]),
                "sha256": img["sha256"],
                "phash": img["perceptual_hash"],
                "width": img["width"],
                "height": img["height"],
                "file_size": img["file_size_bytes"],
                "included_in_export": not failed,
            })

    # listings.csv / .jsonl
    with (annotation_ready_dir / "listings.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        for r in ready_rows:
            writer.writerow(r)
    with (annotation_ready_dir / "listings.jsonl").open("w", encoding="utf-8") as f:
        for r in ready_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    (annotation_ready_dir / "images_manifest.json").write_text(
        json.dumps(images_manifest, indent=2), encoding="utf-8"
    )

    # excluded
    with (excluded_dir / "excluded_listings.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=EXCLUDED_EXPORT_FIELDS)
        writer.writeheader()
        for r in excluded_rows:
            writer.writerow(r)
    with (excluded_dir / "exclusion_reasons.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["listing_id", "reason_code", "reason_detail"])
        writer.writeheader()
        for r in exclusion_reasons:
            writer.writerow(r)
    # excluded_records.csv: the single traceable "every excluded record has a
    # reason" view called for in spec section 18/19 (one row per exclusion
    # reason, joined to the listing).
    with (excluded_dir / "excluded_records.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["listing_id", "platform", "reason_code", "reason_detail"])
        writer.writeheader()
        by_listing = {r["listing_id"]: r for r in excluded_rows}
        for r in exclusion_reasons:
            writer.writerow({
                "listing_id": r["listing_id"],
                "platform": by_listing.get(r["listing_id"], {}).get("platform", ""),
                "reason_code": r["reason_code"],
                "reason_detail": r["reason_detail"],
            })

    # cleaning report (section 18)
    with (reports_dir / "cleaning_report.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["listing_id", "field", "old_value", "new_value", "reason", "cleaning_rule"])
        writer.writeheader()
        for r in cleaning_log:
            writer.writerow(r)

    # missing-values report (section 18) -- one row per ready listing that has
    # at least one missing optional field, wide format.
    missing_fields = [
        "price_missing", "account_age_missing", "seller_rating_missing",
        "review_count_missing", "active_listing_count_missing",
        "description_missing", "location_missing",
    ]
    with (reports_dir / "missing_values.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["listing_id", "platform"] + missing_fields + ["missing_field_count"])
        writer.writeheader()
        for r in ready_rows:
            count = sum(1 for mf in missing_fields if r[mf])
            if count == 0:
                continue
            row_out = {"listing_id": r["listing_id"], "platform": r["platform"], "missing_field_count": count}
            row_out.update({mf: r[mf] for mf in missing_fields})
            writer.writerow(row_out)

    # duplicate report (section 18) -- one row per non-unique listing.
    with (reports_dir / "duplicate_report.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["listing_id", "platform", "duplicate_status", "partner_listing_ids"])
        writer.writeheader()
        for r in ready_rows:
            if r["duplicate_status"] == "unique":
                continue
            partners = sorted(set(duplicate_group_map.get(r["listing_id"], [])))
            writer.writerow({
                "listing_id": r["listing_id"], "platform": r["platform"],
                "duplicate_status": r["duplicate_status"],
                "partner_listing_ids": ";".join(partners),
            })

    # image validation table (section 13) -- one row per product image,
    # covering both copied and (if any) failed-validation images.
    with (reports_dir / "image_validation.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "listing_id", "image_id", "image_path", "is_primary",
            "sha256", "phash", "width", "height", "file_size", "included_in_export",
        ])
        writer.writeheader()
        for r in image_validation_rows:
            writer.writerow(r)

    # reference data (static copies of source config, not a live dependency)
    with (reference_dir / "category_mapping.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["category", "target_pct"])
        for cat, pct in zip(_dbutil.KNOWN_CATEGORIES, [15, 12, 5, 10, 10, 8, 6, 10, 10, 7, 5, 2]):
            writer.writerow([cat, pct])
    with (reference_dir / "platform_mapping.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["platform", "target_count", "target_ratio"])
        writer.writerow(["carousell", 1500, 0.60])
        writer.writerow(["mudah", 1000, 0.40])
    schema_doc = {
        "listing_id": {"type": "string (uuid)", "nullable": False, "source": "listings.listing_id"},
        "platform": {"type": "string enum[carousell,mudah]", "nullable": False, "source": "listings.platform"},
        "marketplace_listing_id": {"type": "string", "nullable": True, "source": "listings.marketplace_listing_id"},
        "source_url": {"type": "string (url)", "nullable": True, "source": "listings.source_url"},
        "category": {"type": "string enum (12 categories)", "nullable": True, "source": "listings.category"},
        "title": {"type": "string", "nullable": True, "source": "listings.title", "note": "PII-redacted in this copy where applicable"},
        "description": {"type": "string", "nullable": True, "source": "listings.description", "note": "PII-redacted in this copy where applicable"},
        "condition": {"type": "string enum[new,like_new,good,fair,poor,unknown]", "nullable": False, "source": "computed from listings.condition", "note": "standardized; see condition_raw for original text"},
        "condition_raw": {"type": "string", "nullable": True, "source": "listings.condition", "note": "original marketplace wording, unmapped"},
        "price": {"type": "float", "nullable": True, "source": "listings.price"},
        "price_missing": {"type": "bool", "nullable": False, "source": "computed"},
        "currency": {"type": "string", "nullable": True, "source": "listings.currency", "note": "normalized RM->MYR in this copy"},
        "location_state": {"type": "string", "nullable": True, "source": "computed from listings.location_state", "note": "canonical Malaysian state/territory name or an accepted region value (West Malaysia/East Malaysia/Nationwide); NULL if the original text was not a real location (see location_state_invalid)"},
        "location_state_raw": {"type": "string", "nullable": True, "source": "listings.location_state", "note": "original text, always preserved"},
        "location_state_invalid": {"type": "bool", "nullable": False, "source": "computed", "note": "True when location_state_raw could not be mapped to a state/region and was nulled -- needs human review"},
        "location_city": {"type": "string", "nullable": True, "source": "listings.location_city"},
        "location_missing": {"type": "bool", "nullable": False, "source": "computed", "note": "True when neither a standardized state nor a city is present"},
        "language": {"type": "string enum[en,ms,mixed,other,unknown]", "nullable": False, "source": "computed from listings.language", "note": "standardized; see language_raw for original text; text itself is never translated"},
        "language_raw": {"type": "string", "nullable": True, "source": "listings.language"},
        "account_age_days": {"type": "int", "nullable": True, "source": "listings.account_age_days", "note": "NULL=unknown, 0=genuinely evidenced zero"},
        "account_age_missing": {"type": "bool", "nullable": False, "source": "computed"},
        "seller_rating": {"type": "float", "nullable": True, "source": "listings.seller_rating", "note": "NULL=unknown, 0=genuinely evidenced zero"},
        "seller_rating_missing": {"type": "bool", "nullable": False, "source": "computed"},
        "review_count": {"type": "int", "nullable": True, "source": "listings.review_count", "note": "NULL=unknown, 0=genuinely evidenced zero (page stated 'no reviews yet')"},
        "review_count_missing": {"type": "bool", "nullable": False, "source": "computed"},
        "active_listing_count": {"type": "int", "nullable": True, "source": "listings.active_listing_count", "note": "NULL=unknown, 0=genuinely evidenced zero"},
        "active_listing_count_missing": {"type": "bool", "nullable": False, "source": "computed"},
        "description_missing": {"type": "bool", "nullable": False, "source": "computed"},
        "captured_at": {"type": "string (iso timestamp)", "nullable": True, "source": "listings.captured_at"},
        "ai_provider": {"type": "string", "nullable": True, "source": "listings.ai_provider"},
        "ai_model": {"type": "string", "nullable": True, "source": "listings.ai_model"},
        "ai_prompt_version": {"type": "string", "nullable": True, "source": "listings.ai_prompt_version"},
        "image_count": {"type": "int", "nullable": False, "source": "computed: count of images/<platform>/<listing_id>/"},
        "primary_image_path": {"type": "string (relative path)", "nullable": True, "source": "computed from images.is_primary"},
        "reused_image_indicator": {"type": "bool", "nullable": False, "source": "computed: listing appears in a cross-listing near-duplicate image group (see dataset_validation_report.md)"},
        "contains_redacted_pii": {"type": "bool", "nullable": False, "source": "computed: title/description contains a '[REDACTED]' token left by the source collector's capture-time PII scrubber"},
        "redacted_pii_count": {"type": "int", "nullable": False, "source": "computed", "note": "count of '[REDACTED]' tokens; the source pipeline does not persist which PII *type* (phone/email/bank/etc) was scrubbed, so a per-type breakdown is not derivable here -- see module docstring in export_annotation_dataset.py"},
        "duplicate_status": {"type": "string enum[unique,possible_duplicate,exact_duplicate]", "nullable": False, "source": "computed from dataset_validation_summary.json duplicate/near-duplicate groups"},
        "annotation_readiness": {"type": "string enum[ready,ready_with_missing,needs_review]", "nullable": False, "source": "computed", "note": "'exclude' listings never reach this file -- they are split out by validate_dataset.py before export"},
        "validation_status": {"type": "string enum[valid]", "nullable": False, "source": "computed by validate_dataset.py; annotation_ready only ever contains 'valid'"},
        "_excluded_by_design": [
            "ai_extracted (raw structured JSON)", "human_corrections_json", "review_audit_json",
            "status_history_json", "screenshot_path", "seller_screenshot_path", "staging_text_path",
            "any fraud/scam-judgement field (none exist in the source schema)",
        ],
    }
    (reference_dir / "schema.json").write_text(json.dumps(schema_doc, indent=2), encoding="utf-8")

    # redactions log
    with (reports_dir / "redactions_applied.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["listing_id", "field", "pattern_types"])
        writer.writeheader()
        for r in redaction_log:
            writer.writerow(r)

    readiness_counts: dict[str, int] = {}
    duplicate_counts: dict[str, int] = {}
    for r in ready_rows:
        readiness_counts[r["annotation_readiness"]] = readiness_counts.get(r["annotation_readiness"], 0) + 1
        duplicate_counts[r["duplicate_status"]] = duplicate_counts.get(r["duplicate_status"], 0) + 1

    return {
        "annotation_ready_count": len(ready_rows),
        "excluded_count": len(excluded_rows),
        "redactions_applied": len(redaction_log),
        "cleaning_changes_applied": len(cleaning_log),
        "images_copied": len(images_manifest),
        "annotation_readiness_counts": readiness_counts,
        "duplicate_status_counts": duplicate_counts,
        "location_state_invalid_count": sum(1 for r in ready_rows if r["location_state_invalid"]),
        "condition_uncertain_count": sum(1 for r in ready_rows if r["condition"] == "unknown" and r["condition_raw"]),
        "language_uncertain_count": sum(1 for r in ready_rows if r["language"] == "unknown" and r["language_raw"]),
        "contains_redacted_pii_count": sum(1 for r in ready_rows if r["contains_redacted_pii"]),
        "images_validated": len(image_validation_rows),
        "images_failed_validation": sum(1 for r in image_validation_rows if not r["included_in_export"]),
    }


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", required=True, type=Path)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parent.parent
    result = run(args.source_repo, workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _main()
