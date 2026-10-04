"""Independent validation audit of the approved GuardianLens listings.

Reads the source collector DB and source image files READ-ONLY. Writes two
reports into this workspace's reports/ folder:

  - reports/dataset_validation_summary.json  (machine-readable)
  - reports/dataset_validation_report.md     (human-readable)
  - reports/per_listing_validation.json      (per-listing classification,
                                               consumed by export_annotation_dataset.py)

Never writes anything into the source repository.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _dbutil  # noqa: E402
import _piiscan  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    print("Pillow is required: pip install -r requirements.txt", file=sys.stderr)
    raise

TEXT_FIELDS = [
    "title", "description", "category", "condition", "price", "currency",
    "location_state", "location_city", "language",
]
SELLER_FIELDS = ["account_age_days", "seller_rating", "review_count", "active_listing_count"]
PLACEHOLDER_TOKENS = {"n/a", "na", "unknown", "test", "lorem ipsum", ""}


def is_placeholder(value) -> bool:
    if value is None:
        return False
    s = str(value).strip().lower()
    if s in PLACEHOLDER_TOKENS:
        return True
    # repeated-character junk like "aaaaa" or "-----"
    if len(s) >= 5 and len(set(s)) == 1:
        return True
    return False


def classify_seller_field(value) -> str:
    if value is None:
        return "null"
    try:
        if float(value) == 0:
            return "zero"
    except (TypeError, ValueError):
        pass
    return "value"


class UnionFind:
    def __init__(self):
        self.parent: dict = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def hamming(hex_a: str, hex_b: str) -> int:
    return bin(int(hex_a, 16) ^ int(hex_b, 16)).count("1")


def find_near_duplicate_image_groups(images: list) -> dict:
    """8-band LSH over the 64-bit dHash (8 bits/band).

    Pigeonhole guarantee: two hashes with true Hamming distance <=5 cannot
    differ in more than 5 of the 8 bands, so they are guaranteed to share at
    least 3 identical bands and will be found as band-collision candidates.

    Returns groups split into:
      - within_listing: all member images belong to the same listing_id
        (expected -- multiple angles/photos of the same product, NOT a
        fraud signal, not something to surface prominently).
      - cross_listing: member images span 2+ distinct listing_ids (the
        actual "reused/stock image" signal worth flagging to annotators).
    """
    by_id = {}
    listing_of = {}
    bands = defaultdict(list)
    for row in images:
        phash = row["perceptual_hash"]
        if not phash or len(phash) != 16:
            continue
        by_id[row["image_id"]] = phash
        listing_of[row["image_id"]] = row["listing_id"]
        for band_idx in range(8):
            chunk = phash[band_idx * 2:(band_idx + 1) * 2]
            bands[(band_idx, chunk)].append(row["image_id"])

    uf = UnionFind()
    checked_pairs = set()
    for members in bands.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                pair = (a, b) if a < b else (b, a)
                if pair in checked_pairs:
                    continue
                checked_pairs.add(pair)
                if hamming(by_id[a], by_id[b]) <= 5:
                    uf.union(a, b)

    groups = defaultdict(list)
    for image_id in by_id:
        groups[uf.find(image_id)].append(image_id)

    within_listing = []
    cross_listing = []
    for members in groups.values():
        if len(members) <= 1:
            continue
        distinct_listings = {listing_of[m] for m in members}
        if len(distinct_listings) > 1:
            cross_listing.append({
                "image_ids": members,
                "listing_ids": sorted(distinct_listings),
            })
        else:
            within_listing.append(members)

    return {"within_listing": within_listing, "cross_listing": cross_listing}


def run(source_repo: Path, workspace: Path) -> dict:
    conn = _dbutil.open_source_db(source_repo)
    try:
        listings = _dbutil.fetch_approved_listings(conn)
        all_images = _dbutil.fetch_images(conn)
    finally:
        conn.close()

    listings_by_id = {row["listing_id"]: row for row in listings}
    images_by_listing = defaultdict(list)
    approved_images = []
    for row in all_images:
        if row["listing_id"] in listings_by_id:
            images_by_listing[row["listing_id"]].append(row)
            approved_images.append(row)

    per_listing: dict[str, dict] = {}
    field_missing_counts = Counter()
    field_placeholder_counts = Counter()
    seller_state_counts = {f: Counter() for f in SELLER_FIELDS}
    platform_counts = Counter()
    category_counts = Counter()
    language_counts = Counter()
    image_count_distribution = Counter()
    pii_findings = Counter()
    pii_hits_by_listing = defaultdict(list)
    structural_findings = Counter()

    # --- Step 1: identity & duplicates (independent re-check) ---
    listing_id_counter = Counter(row["listing_id"] for row in listings)
    duplicate_listing_ids = [lid for lid, c in listing_id_counter.items() if c > 1]

    marketplace_key_counter = Counter()
    url_hash_counter = Counter()
    metadata_sig_counter = Counter()
    for row in listings:
        if row["marketplace_listing_id"]:
            marketplace_key_counter[(row["platform"], row["marketplace_listing_id"])] += 1
        if row["source_url_hash"]:
            url_hash_counter[row["source_url_hash"]] += 1
        if row["metadata_signature"]:
            metadata_sig_counter[row["metadata_signature"]] += 1

    duplicate_marketplace_ids = [k for k, c in marketplace_key_counter.items() if c > 1]
    duplicate_url_hashes = [k for k, c in url_hash_counter.items() if c > 1]
    duplicate_metadata_signatures = [k for k, c in metadata_sig_counter.items() if c > 1]

    repost_candidate_groups = defaultdict(list)
    for row in listings:
        title_key = (row["title"] or "").strip().lower()
        key = (row["platform"], title_key, row["price"])
        if title_key:
            repost_candidate_groups[key].append(row["listing_id"])
    possible_repost_candidates = [v for v in repost_candidate_groups.values() if len(v) > 1]

    # --- Step 2: exact & near-duplicate images ---
    sha_counter = defaultdict(list)
    for row in approved_images:
        if row["sha256"]:
            sha_counter[row["sha256"]].append(row["image_id"])
    exact_duplicate_image_groups = [v for v in sha_counter.values() if len(v) > 1]
    near_dup = find_near_duplicate_image_groups(approved_images)
    near_duplicate_within_listing_groups = near_dup["within_listing"]
    near_duplicate_cross_listing_groups = near_dup["cross_listing"]

    # --- Steps 3-8: per-listing checks ---
    images_root = _dbutil.images_root_for(source_repo)

    for row in listings:
        lid = row["listing_id"]
        reasons = []
        missing_fields = []
        platform_counts[row["platform"]] += 1
        category_counts[row["category"] or "<missing>"] += 1
        language_counts[row["language"] or "<missing>"] += 1

        # text fields
        for field in TEXT_FIELDS:
            value = row[field]
            if value is None or (isinstance(value, str) and value.strip() == ""):
                field_missing_counts[field] += 1
                missing_fields.append(field)
            elif is_placeholder(value):
                field_placeholder_counts[field] += 1
                reasons.append(f"placeholder_value:{field}")

        if row["price"] is not None:
            try:
                price = float(row["price"])
                if price < 0:
                    reasons.append("negative_price")
                    structural_findings["negative_price"] += 1
                elif price == 0:
                    reasons.append("zero_price_meaning_unverified")
                    structural_findings["zero_price_meaning_unverified"] += 1
            except (TypeError, ValueError):
                reasons.append("non_numeric_price")
                structural_findings["non_numeric_price"] += 1

        if row["platform"] not in _dbutil.KNOWN_PLATFORMS:
            reasons.append("unknown_platform")
            structural_findings["unknown_platform"] += 1
        if row["category"] and row["category"] not in _dbutil.KNOWN_CATEGORIES:
            reasons.append("unknown_category")
            structural_findings["unknown_category"] += 1
        if row["currency"] and str(row["currency"]).strip().upper() not in ("MYR",):
            # Known benign variant seen in this dataset: "RM" (Ringgit symbol)
            # instead of the ISO code "MYR" -- not corruption, just an
            # inconsistent representation. Normalized in the annotation-ready
            # COPY only (see export_annotation_dataset.py); source untouched.
            reasons.append("currency_symbol_variant")
            structural_findings["currency_symbol_variant"] += 1

        for field in TEXT_FIELDS:
            value = row[field]
            if isinstance(value, str):
                try:
                    value.encode("utf-8")
                except UnicodeEncodeError:
                    reasons.append(f"encoding_error:{field}")
                    structural_findings["encoding_error"] += 1

        # seller/behavioural fields
        seller_state = {}
        for field in SELLER_FIELDS:
            state = classify_seller_field(row[field])
            seller_state[field] = state
            seller_state_counts[field][state] += 1
            if state == "value":
                try:
                    v = float(row[field])
                    if field == "seller_rating" and not (0 <= v <= 5):
                        reasons.append("implausible_seller_rating")
                        structural_findings["implausible_seller_rating"] += 1
                    if field != "seller_rating" and v < 0:
                        reasons.append(f"negative_{field}")
                        structural_findings[f"negative_{field}"] += 1
                except (TypeError, ValueError):
                    pass

        # PII re-audit
        for field in ["title", "description", "condition", "location_state", "location_city"]:
            hits = _piiscan.scrub_findings(row[field])
            if hits:
                pii_hits_by_listing[lid].extend(hits)
                for h in hits:
                    pii_findings[h] += 1

        # images
        listing_images = images_by_listing.get(lid, [])
        image_count_distribution[len(listing_images)] += 1
        image_ids_ok, image_ids_failed = [], []
        if not listing_images:
            reasons.append("missing_product_images")

        for img in listing_images:
            img_path = source_repo / img["storage_path"]
            fail_reason = None
            if not img_path.exists():
                fail_reason = "file_missing"
            elif img_path.stat().st_size == 0:
                fail_reason = "zero_byte_file"
            else:
                try:
                    with Image.open(img_path) as im:
                        im.verify()
                    with Image.open(img_path) as im:
                        fmt = im.format
                        width, height = im.size
                    if fmt not in ("JPEG", "PNG", "WEBP"):
                        fail_reason = f"unsupported_format:{fmt}"
                    elif width < 20 or height < 20:
                        fail_reason = f"implausible_dimensions:{width}x{height}"
                    else:
                        actual_sha = __import__("hashlib").sha256(img_path.read_bytes()).hexdigest()
                        if img["sha256"] and actual_sha != img["sha256"]:
                            fail_reason = "sha256_mismatch"
                except Exception as exc:  # noqa: BLE001
                    fail_reason = f"corrupt_or_unreadable:{exc.__class__.__name__}"

            if fail_reason:
                image_ids_failed.append(img["image_id"])
                reasons.append(f"image_integrity:{img['image_id']}:{fail_reason}")
            else:
                image_ids_ok.append(img["image_id"])

        if listing_images and not image_ids_ok:
            reasons.append("all_images_failed_integrity")

        hard_fail = (
            "missing_product_images" in reasons
            or "all_images_failed_integrity" in reasons
            or any(r.startswith("image_integrity:") and image_ids_ok == [] for r in reasons)
        )
        status = "needs_attention" if hard_fail else "valid"

        per_listing[lid] = {
            "status": status,
            "reasons": reasons,
            "missing_fields": missing_fields,
            "seller_field_state": seller_state,
            "image_ids_ok": image_ids_ok,
            "image_ids_failed": image_ids_failed,
        }

    valid_count = sum(1 for v in per_listing.values() if v["status"] == "valid")
    needs_attention_count = sum(1 for v in per_listing.values() if v["status"] == "needs_attention")

    summary = {
        "total_approved_listings": len(listings),
        "total_valid_for_annotation": valid_count,
        "total_needs_attention": needs_attention_count,
        "duplicate_listing_ids": duplicate_listing_ids,
        "duplicate_marketplace_ids": [list(k) for k in duplicate_marketplace_ids],
        "duplicate_source_url_hashes": duplicate_url_hashes,
        "duplicate_metadata_signatures": duplicate_metadata_signatures,
        "possible_repost_candidates_group_count": len(possible_repost_candidates),
        "possible_repost_candidates": possible_repost_candidates,
        "exact_duplicate_image_groups_count": len(exact_duplicate_image_groups),
        "exact_duplicate_image_groups": exact_duplicate_image_groups,
        "near_duplicate_within_listing_groups_count": len(near_duplicate_within_listing_groups),
        "near_duplicate_cross_listing_groups_count": len(near_duplicate_cross_listing_groups),
        "near_duplicate_cross_listing_groups": near_duplicate_cross_listing_groups,
        "near_duplicate_cross_listing_listing_ids": sorted(
            {lid for grp in near_duplicate_cross_listing_groups for lid in grp["listing_ids"]}
        ),
        "text_field_missing_counts": dict(field_missing_counts),
        "text_field_placeholder_counts": dict(field_placeholder_counts),
        "seller_field_state_counts": {f: dict(c) for f, c in seller_state_counts.items()},
        "platform_distribution": dict(platform_counts),
        "category_distribution": dict(category_counts),
        "language_distribution": dict(language_counts),
        "image_count_distribution": dict(image_count_distribution),
        "pii_reaudit_finding_counts": dict(pii_findings),
        "pii_reaudit_listings_with_hits": len(pii_hits_by_listing),
        "structural_finding_counts": dict(structural_findings),
        "total_approved_images": len(approved_images),
    }

    workspace_reports = workspace / "reports"
    workspace_reports.mkdir(parents=True, exist_ok=True)
    (workspace_reports / "dataset_validation_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (workspace_reports / "per_listing_validation.json").write_text(
        json.dumps(per_listing, indent=2), encoding="utf-8"
    )

    report_md = _render_markdown_report(summary)
    (workspace_reports / "dataset_validation_report.md").write_text(report_md, encoding="utf-8")

    return summary


def _render_markdown_report(s: dict) -> str:
    lines = [
        "# GuardianLens Dataset Validation Report",
        "",
        "Independent read-only audit of the source collector database's approved listings. "
        "Source database was never modified by this audit.",
        "",
        "## Totals",
        f"- Total approved listings inspected: {s['total_approved_listings']}",
        f"- Valid for annotation: {s['total_valid_for_annotation']}",
        f"- Needs attention (excluded from annotation_ready): {s['total_needs_attention']}",
        f"- Total approved images: {s['total_approved_images']}",
        "",
        "## Duplicate checks (independent re-check, DB already enforces uniqueness at approval time)",
        f"- Duplicate listing_id: {len(s['duplicate_listing_ids'])}",
        f"- Duplicate (platform, marketplace_listing_id): {len(s['duplicate_marketplace_ids'])}",
        f"- Duplicate source_url_hash: {len(s['duplicate_source_url_hashes'])}",
        f"- Duplicate metadata_signature: {len(s['duplicate_metadata_signatures'])}",
        f"- Possible repost candidate groups (same platform+title+price, heuristic, NOT auto-excluded): {s['possible_repost_candidates_group_count']}",
        "",
        "## Image duplicates",
        f"- Exact SHA-256 duplicate groups among approved images: {s['exact_duplicate_image_groups_count']}",
        f"- Near-duplicate groups WITHIN the same listing (dHash Hamming distance <=5 -- expected, multiple angles/photos of one product, NOT a finding): {s['near_duplicate_within_listing_groups_count']}",
        f"- Near-duplicate groups ACROSS DIFFERENT listings (heuristic reused/stock-image signal, NOT auto-excluded, worth annotator review): {s['near_duplicate_cross_listing_groups_count']}",
        f"- Distinct listings touched by a cross-listing near-duplicate group: {len(s['near_duplicate_cross_listing_listing_ids'])}",
        "",
        "## Text field completeness (missing/null counts)",
    ]
    for field, count in sorted(s["text_field_missing_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"- {field}: {count} missing")
    lines.append("")
    lines.append("## Text field placeholder-value counts")
    for field, count in sorted(s["text_field_placeholder_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"- {field}: {count} placeholder-like values")
    lines.append("")
    lines.append("## Seller/behavioural field completeness (null = genuinely missing, zero = evidenced zero, value = positive)")
    for field, counts in s["seller_field_state_counts"].items():
        lines.append(f"- {field}: null={counts.get('null', 0)}, zero={counts.get('zero', 0)}, value={counts.get('value', 0)}")
    lines.append("")
    lines.append("## Platform distribution")
    for k, v in s["platform_distribution"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Category distribution")
    for k, v in sorted(s["category_distribution"].items(), key=lambda kv: -kv[1]):
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Language distribution")
    for k, v in s["language_distribution"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Image-count-per-listing distribution")
    for k, v in sorted(s["image_count_distribution"].items()):
        lines.append(f"- {k} image(s): {v} listing(s)")
    lines.append("")
    lines.append("## Independent PII re-audit")
    lines.append(f"- Listings with at least one residual PII-shaped match: {s['pii_reaudit_listings_with_hits']}")
    for k, v in s["pii_reaudit_finding_counts"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Structural finding counts")
    for k, v in s["structural_finding_counts"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Unresolved issues")
    lines.append(
        "- Listings classified `needs_attention` are excluded from `data/annotation_ready/` and "
        "moved to `data/excluded/` with reasons in `exclusion_reasons.csv` -- see export_annotation_dataset.py output."
    )
    lines.append(
        "- Near-duplicate image groups and repost candidates are reported but NOT automatically "
        "excluded, per instructions -- review manually if pursuing dataset-split leakage prevention."
    )
    lines.append("")
    lines.append("## Recommended next actions")
    lines.append("- Review `data/excluded/exclusion_reasons.csv` before annotation begins.")
    lines.append("- Review near-duplicate image groups before any future train/val/test split (see docs/DATASET_SPLIT_SAFETY.md).")
    lines.append("- Residual PII hits (if any) were redacted only in the annotation-ready COPY -- see reports/redactions_applied.csv after export.")
    return "\n".join(lines) + "\n"


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", required=True, type=Path)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parent.parent
    summary = run(args.source_repo, workspace)
    print(json.dumps({k: summary[k] for k in (
        "total_approved_listings", "total_valid_for_annotation", "total_needs_attention"
    )}, indent=2))


if __name__ == "__main__":
    _main()
