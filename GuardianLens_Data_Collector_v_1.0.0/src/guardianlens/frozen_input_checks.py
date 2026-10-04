"""Offline collection-quality checks. These never assign fraud labels or edit rows."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable

from PIL import Image

from .dedupe import metadata_signature
from .pii import residual_pii
from .states import can_transition
from .validation import validate_fields

CONTENT_FIELDS = (
    "title", "description", "category", "condition", "price", "currency",
    "location_state", "location_city", "account_age_days", "seller_rating",
    "review_count", "active_listing_count", "language",
)
SELLER_FIELDS = ("account_age_days", "seller_rating", "review_count", "active_listing_count")
EVIDENCE_FIELDS = ("screenshot_path", "seller_screenshot_path", "staging_text_path")


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def dump_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def dump_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            safe = {}
            for field in fields:
                value = row.get(field)
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                if isinstance(value, str) and (
                    value.startswith(("\t", "\r", "\n"))
                    or value.lstrip().startswith(("=", "+", "-", "@"))
                ):
                    value = "'" + value
                safe[field] = value
            writer.writerow(safe)


def missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _json_object(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def owned_asset(project: Path, relative: str | None, expected_parent: Path) -> Path | None:
    if not relative or Path(relative).is_absolute():
        return None
    candidate = (project / relative).resolve()
    if candidate.parent != expected_parent.resolve() or not candidate.is_file():
        return None
    return candidate


def image_check(project: Path, row: dict) -> dict:
    """Decode stored bytes and independently recompute SHA-256 and 64-bit dHash."""
    result = {"image_id": row["image_id"], "listing_id": row["listing_id"], "issues": []}
    expected = project / "data/images" / row["platform"] / row["listing_id"]
    path = owned_asset(project, row.get("storage_path"), expected)
    if path is None:
        result["issues"].append("missing_or_unsafe_image")
        return result
    try:
        data = path.read_bytes()
        if len(data) != row["file_size_bytes"]:
            result["issues"].append("image_size_mismatch")
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            result["issues"].append("image_sha256_mismatch")
        with Image.open(io.BytesIO(data)) as picture:
            if picture.width * picture.height > 100_000_000:
                raise ValueError("image pixel budget exceeded")
            picture.verify()
        with Image.open(io.BytesIO(data)) as picture:
            picture.load()
            result["format"] = picture.format
            if picture.format not in {"JPEG", "PNG", "WEBP"}:
                result["issues"].append("unsupported_image_format")
            if picture.size != (row["width"], row["height"]):
                result["issues"].append("image_dimensions_mismatch")
            if picture.getexif():
                result["issues"].append("image_exif_present")
            gray = picture.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
            reader = getattr(gray, "get_flattened_data", gray.getdata)
            pixels = list(reader())
            bits = [pixels[y * 9 + x] > pixels[y * 9 + x + 1] for y in range(8) for x in range(8)]
            calculated = f"{sum(int(bit) << (63 - i) for i, bit in enumerate(bits)):016x}"
            if calculated != row["perceptual_hash"]:
                result["issues"].append("image_dhash_mismatch")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        result["issues"].append("image_decode_error:" + type(exc).__name__)
    return result


def reconcile_handoff(handoff: Path, listings: list[dict], counts: dict,
                      con: sqlite3.Connection | None = None) -> dict:
    """Compare captured handoff values with the frozen database, not with live state."""
    manifest_path = handoff / "manifest.json"
    if not manifest_path.is_file():
        return {"available": False, "current": False, "reason": "handoff_manifest_missing"}
    manifest = _json_object(manifest_path.read_text(encoding="utf-8"))
    invalid_files = []
    for name, item in manifest.get("files", {}).items():
        path = (handoff / name).resolve()
        if not path.is_relative_to(handoff.resolve()) or not path.is_file():
            invalid_files.append(name)
        elif hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
            invalid_files.append(name)
        elif path.stat().st_size != item.get("bytes"):
            invalid_files.append(name)
    differences = []
    file = handoff / "master/listings.csv"
    captured = {}
    duplicate_ids = []
    if file.is_file():
        with file.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                key = row.get("listing_id")
                if key in captured:
                    duplicate_ids.append(key)
                captured[key] = row
    authoritative = {row["listing_id"]: row for row in listings}
    for key in sorted(set(captured) | set(authoritative)):
        if key not in captured or key not in authoritative:
            differences.append({"listing_id": key, "field": "row_membership"})
            continue
        for field, value in captured[key].items():
            if field not in authoritative[key]:
                continue
            expected = authoritative[key][field]
            rendered = "" if expected is None else str(expected)
            if value.startswith("'") and value[1:] == rendered:
                value = value[1:]
            if value != rendered:
                differences.append({"listing_id": key, "field": field})
    manifest_counts = manifest.get("counts", {})
    manifest_counts = dict(manifest_counts)
    if isinstance(manifest_counts.get("by_status"), dict):
        manifest_counts["by_status"] = {k: v for k, v in manifest_counts["by_status"].items() if v}
    count_differences = {
        key: {"handoff": manifest_counts.get(key), "frozen": value}
        for key, value in counts.items() if manifest_counts.get(key) != value
    }
    approved_ids = {r["listing_id"] for r in listings if r["status"] == "approved"}
    pilot = handoff / "test/annotation_test.csv"
    pilot_ids = []
    if pilot.is_file():
        with pilot.open(encoding="utf-8-sig", newline="") as handle:
            pilot_ids = [r["listing_id"] for r in csv.DictReader(handle)]
    pilot_matches = set(pilot_ids) == approved_ids and len(pilot_ids) == len(approved_ids)
    additional = {}
    if con is not None:
        mappings = {
            "master/images.csv": ("images", "image_id"),
            "master/source_rows.csv": ("capture_batch_items", "batch_item_id"),
            "audit/warnings.csv": ("warnings", "warning_id"),
            "audit/review_actions.csv": ("review_actions", "review_id"),
            "audit/status_history.csv": ("status_history", "history_id"),
            "audit/ai_extractions.csv": ("ai_extractions", "extraction_id"),
            "audit/capture_attempts.csv": ("capture_batch_attempts", "attempt_id"),
            "audit/processing_runs.csv": ("processing_runs", "run_id"),
            "test/annotation_test.csv": ("listings", "listing_id"),
        }
        for status in {r["status"] for r in listings}:
            mappings[f"by_status/{status}.csv"] = ("listings", "listing_id")
        for filename, (table, primary) in mappings.items():
            path = handoff / filename
            expected_rows = [dict(r) for r in con.execute(f'SELECT * FROM "{table}"')]
            if filename == "test/annotation_test.csv":
                expected_rows = [r for r in expected_rows if r["status"] == "approved"]
            elif filename.startswith("by_status/"):
                expected_rows = [r for r in expected_rows if r["status"] == Path(filename).stem]
            # Discover the actual primary key rather than assuming a historical name.
            if expected_rows and primary not in expected_rows[0]:
                primary = next(r["name"] for r in con.execute(f'PRAGMA table_info("{table}")') if r["pk"])
            expected_index = {r[primary]: r for r in expected_rows}
            with path.open(encoding="utf-8-sig", newline="") if path.is_file() else io.StringIO("") as handle:
                csv_rows = list(csv.DictReader(handle))
            actual_index = {r.get(primary): r for r in csv_rows}
            field_changes = Counter()
            for key in set(expected_index) & set(actual_index):
                for field, actual_value in actual_index[key].items():
                    if field not in expected_index[key]:
                        continue
                    value = expected_index[key][field]
                    rendered = "" if value is None else str(value)
                    if actual_value != rendered and actual_value != "'" + rendered:
                        field_changes[field] += 1
            additional[filename] = {
                "file_present": path.is_file(), "frozen_rows": len(expected_rows), "handoff_rows": len(csv_rows),
                "missing_ids": sorted(set(expected_index) - set(actual_index)),
                "extra_ids": sorted(str(k) for k in set(actual_index) - set(expected_index)),
                "duplicate_ids": len(csv_rows) - len(actual_index), "value_difference_counts": dict(field_changes),
            }
    additional_differences = any(not r["file_present"] or r["missing_ids"] or r["extra_ids"]
                                 or r["duplicate_ids"] or r["value_difference_counts"] for r in additional.values())
    return {
        "available": True, "generated_at": manifest.get("generated_at"),
        "current": not (invalid_files or differences or count_differences or duplicate_ids or additional_differences) and pilot_matches,
        "invalid_files": invalid_files, "duplicate_listing_ids": duplicate_ids,
        "field_differences": differences, "count_differences": count_differences,
        "approved_pilot_matches": pilot_matches,
        "additional_csv_comparisons": additional,
        "comparison_limitations": "Common source columns compared exactly. Legacy redaction/JSON formatting/path normalization can also cause differences; differences do not alone prove staleness. Derived quality reports are re-created independently, not trusted.",
        "warning": "Current means equal to this frozen database, never a freshness guarantee for future live approvals.",
    }


def analyze(con: sqlite3.Connection, project: Path, categories: list[str], progress: Callable[[str], None]) -> dict:
    """Inspect every frozen listing; return private findings and aggregate counts."""
    rows = [dict(row) for row in con.execute("SELECT * FROM listings ORDER BY listing_id")]
    images = [dict(row) for row in con.execute("SELECT * FROM images ORDER BY listing_id,source_position,image_id")]
    grouped: dict[str, dict[str, list]] = {}
    for table in ("images", "warnings", "ai_extractions", "review_actions", "status_history"):
        group: dict[str, list] = defaultdict(list)
        for item in con.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
            group[item["listing_id"]].append(dict(item))
        grouped[table] = group
    image_results = []
    image_issues: dict[str, list] = defaultdict(list)
    for index, image in enumerate(images, 1):
        result = image_check(project, image)
        image_results.append(result)
        image_issues[image["listing_id"]].extend(result["issues"])
        if index % 500 == 0:
            progress(f"Verified frozen product images: {index}/{len(images)}")
    exact_text: dict[str, list] = defaultdict(list)
    exact_sha: dict[str, set] = defaultdict(set)
    for row in rows:
        if row.get("description"):
            exact_text[row["description"]].append(row["listing_id"])
    for image in images:
        exact_sha[image["sha256"]].add(image["listing_id"])
    duplicate_text_ids = {key for ids in exact_text.values() if len(ids) > 1 for key in ids}
    duplicate_image_ids = {key for ids in exact_sha.values() if len(ids) > 1 for key in ids}
    approved_signatures: dict[str, list] = defaultdict(list)
    approved_sources: dict[tuple, list] = defaultdict(list)
    for row in rows:
        if row["status"] == "approved":
            try:
                signature = metadata_signature(row["platform"], row["title"], row["description"], row["price"])
            except (TypeError, ValueError, AttributeError):
                signature = None  # Invalid source values remain visible in field findings.
            if signature:
                approved_signatures[signature].append(row["listing_id"])
            if row.get("marketplace_listing_id"):
                approved_sources[(row["platform"], row["marketplace_listing_id"])].append(row["listing_id"])
    approved_duplicate_ids = {key for group in (approved_signatures, approved_sources) for ids in group.values() if len(ids) > 1 for key in ids}
    checks = []
    for row in rows:
        key = row["listing_id"]
        findings = list(validate_fields(row, categories))
        def add(code: str, field: str | None = None) -> None:
            findings.append({"code": code, "field": field})
        product = grouped["images"].get(key, [])
        if not product:
            add("no_product_images")
        elif sum(bool(i["is_primary"]) for i in product) != 1:
            add("invalid_primary_image_count")
        for issue in sorted(set(image_issues[key])):
            add(issue)
        evidence = {}
        for field in EVIDENCE_FIELDS:
            parent = project / "data/private/staging" if field == "staging_text_path" else project / "data/private/screenshots" / row["platform"] / key
            path = owned_asset(project, row.get(field), parent)
            evidence[field] = path is not None
            if path is None:
                add("private_evidence_unavailable", field)
        staging_path = owned_asset(project, row.get("staging_text_path"), project / "data/private/staging")
        staging = _json_object(staging_path.read_text(encoding="utf-8")) if staging_path else {}
        attempts = sorted(grouped["ai_extractions"].get(key, []), key=lambda x: (x["created_at"], x["extraction_id"]))
        successful = [a for a in attempts if a["status"] == "success"]
        outputs = [_json_object(a.get("structured_output")) for a in successful]
        if not successful:
            add("no_successful_ai_provenance")
        for field in CONTENT_FIELDS:
            values = [o.get(field) for o in outputs if not missing(o.get(field))]
            if missing(row.get(field)) and values:
                add("current_missing_but_prior_ai_value_exists", field)
            if len({json.dumps(v, sort_keys=True) for v in values}) > 1:
                add("ai_attempts_disagree", field)
        corrections = grouped["review_actions"].get(key, [])
        edited_fields = set()
        for action in corrections:
            if action["action"] != "edit":
                continue
            before, after = _json_object(action.get("previous_data")), _json_object(action.get("updated_data"))
            edited_fields.update(after)
            for field in SELLER_FIELDS:
                if field in after and missing(before.get(field)) and after[field] == 0:
                    add("manual_unknown_changed_to_zero", field)
            if not action.get("reason"):
                add("human_edit_without_reason")
        latest = outputs[-1] if outputs else {}
        for field in CONTENT_FIELDS:
            if successful and row.get(field) != latest.get(field) and field not in edited_fields:
                add("current_differs_from_latest_ai_without_field_edit", field)
        history = sorted(grouped["status_history"].get(key, []), key=lambda x: x["timestamp"])
        prior = None
        for entry in history:
            if entry["from_status"] != prior or (prior and not can_transition(prior, entry["to_status"])):
                add("status_history_inconsistent")
            prior = entry["to_status"]
        if prior != row["status"]:
            add("status_history_current_mismatch")
        approvals = [entry for entry in history if entry["to_status"] == "approved"]
        automatic = any(re.search(r"auto[- ]approved|auto[- ]finished", entry.get("reason") or "", re.I) for entry in approvals)
        if automatic:
            add("automatic_approval_requires_evidence_review")
        if row["status"] == "approved" and not any(a["action"] == "approve" for a in corrections):
            add("approval_action_missing")
        if row["status"] == "approved" and not row.get("approved_at"):
            add("approval_timestamp_missing")
        for field in ("page_title", "source_url", "seller_url"):
            if residual_pii(row.get(field)):
                add("pii_pattern_in_private_provenance", field)
        for action in corrections:
            if residual_pii(action.get("reason")):
                add("pii_pattern_in_review_reason")
        for field in ("title", "description"):
            value = row.get(field) or ""
            if re.search(r"<\s*/?\s*(?:div|p|span|script|html|br)\b|&(?:nbsp|amp|lt|gt);", value, re.I):
                add("text_formatting_contamination", field)
        if key in duplicate_text_ids:
            add("exact_description_reuse")
        if key in duplicate_image_ids or key in approved_duplicate_ids:
            add("duplicate_association_review")
        warnings = grouped["warnings"].get(key, [])
        if any(w["warning_type"] == "duplicate_image" for w in warnings):
            add("duplicate_images_omitted_from_listing_associations")
        if any(w["warning_type"] == "near_duplicate_image" for w in warnings):
            add("similar_image_warning_not_ground_truth")
        if row["platform"] == "mudah" and (row.get("seller_rating") == 4.7 or row.get("review_count") == 200000):
            add("possible_marketplace_app_metrics_not_seller_metrics")
        text = str(staging.get("visible_text") or "")
        if re.search(r"(?:4\.7\s+200[kK]\+?\s+reviews|download\s+app)", text, re.I):
            add("app_promotion_in_capture_text")
        if row.get("price") == 0:
            add("zero_price_meaning_unverified", "price")
        strict = validate_fields(row, categories)
        strict_codes = {f["code"] for f in strict}
        strict_blocked = bool(strict or not product or image_issues[key] or key in approved_duplicate_ids
                              or sum(bool(i["is_primary"]) for i in product) != 1)
        checks.append({
            "listing_id": key, "platform": row["platform"], "collection_status": row["status"],
            "strict_collection_gate_pass": not strict_blocked, "field_gate_codes": sorted(strict_codes),
            "missing_required_fields": [f["field"] for f in strict if f["code"] == "missing_field"],
            "product_image_count": len(product), "product_integrity_pass": bool(product) and not image_issues[key],
            "private_evidence_available": evidence, "automatic_approval_recorded": automatic,
            "semantic_correctness": "unverified", "findings": findings,
        })
    approved = [r for r in rows if r["status"] == "approved"]
    approved_checks = [r for r in checks if r["collection_status"] == "approved"]
    completeness = []
    for scope, selected in [("all", rows), ("approved", approved), *[(p, [r for r in rows if r["platform"] == p]) for p in ("carousell", "mudah")]]:
        for field in (tuple(rows[0]) if rows else CONTENT_FIELDS):
            populated = sum(not missing(r.get(field)) for r in selected)
            completeness.append({"scope": scope, "field": field, "total": len(selected), "nonempty": populated,
                                 "null": sum(r.get(field) is None for r in selected),
                                 "empty_string": sum(isinstance(r.get(field), str) and not r[field].strip() for r in selected),
                                 "completeness_percent": round(100 * populated / len(selected), 2) if selected else None})
    counts = {table: con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in
              ("listings", "images", "warnings", "review_actions", "status_history", "ai_extractions", "processing_runs")}
    counts["source_rows"] = con.execute("SELECT COUNT(*) FROM capture_batch_items").fetchone()[0]
    counts["capture_attempts"] = con.execute("SELECT COUNT(*) FROM capture_batch_attempts").fetchone()[0]
    counts["approved_annotation_test"] = len(approved)
    counts["by_status"] = dict(Counter(r["status"] for r in rows))
    approved_ids = {r["listing_id"] for r in approved}
    summary = {
        "counts": counts, "approved_by_platform": dict(Counter(r["platform"] for r in approved)),
        "approved_images": sum(i["listing_id"] in approved_ids for i in images),
        "all_image_integrity_failures": sum(bool(r["issues"]) for r in image_results),
        "approved_strict_gate_pass": sum(r["strict_collection_gate_pass"] for r in approved_checks),
        "approved_strict_gate_blocked": sum(not r["strict_collection_gate_pass"] for r in approved_checks),
        "approved_automatic_approval_recorded": sum(r["automatic_approval_recorded"] for r in approved_checks),
        "approved_missing_private_evidence": {f: sum(not r["private_evidence_available"][f] for r in approved_checks) for f in EVIDENCE_FIELDS},
        "approved_semantically_verified": 0,
        "approved_finding_counts": dict(Counter(f["code"] for r in approved_checks for f in r["findings"])),
        "all_finding_counts": dict(Counter(f["code"] for r in checks for f in r["findings"])),
        "limitations": [
            "Passing structural checks is not proof of accurate extraction, human review, non-fraud, or training suitability.",
            "No external evidence, fresh extraction, OCR, fraud labels, annotation tables or training were used.",
            "Exact image duplicates may have been omitted; warning absence cannot reconstruct lost associations.",
            "Image bytes and metadata are checked; image pixels and names in free text still require privacy review.",
            "All source values, including questionable or missing values, are preserved unchanged in the private backup.",
        ],
    }
    return {"rows": rows, "images": images, "approved": approved, "checks": checks,
            "approved_checks": approved_checks, "image_checks": image_results,
            "completeness": completeness, "summary": summary, "grouped": grouped}


def write_review_page(path: Path, result: dict) -> None:
    """Local, read-only evidence browser. No API calls or save/approve controls."""
    cases = []
    indexed = {r["listing_id"]: r for r in result["approved_checks"]}
    for row in result["approved"]:
        key = row["listing_id"]
        cases.append({"record": row, "check": indexed[key], **{
            table: result["grouped"][table].get(key, [])
            for table in ("images", "ai_extractions", "review_actions", "status_history")
        }})
    payload = json.dumps(cases, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    page = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>GuardianLens frozen verification</title>
<style>body{font:16px/1.5 system-ui;margin:24px;background:#f7f7f5;color:#172026}header{max-width:1000px}input,select,button{font:inherit;padding:8px}main{display:grid;grid-template-columns:280px minmax(0,1fr);gap:24px}nav{max-height:75vh;overflow:auto}nav button{display:block;width:100%;text-align:left;margin:4px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:16px}img{max-width:280px;max-height:260px;margin:6px}dt{font-weight:700}dd{margin:0 0 12px;white-space:pre-wrap}section{min-width:0}a{color:#175596}@media(max-width:700px){main{display:block}nav{max-height:200px}}</style>
<header><h1>Frozen approved-record verification</h1><p>Private local copy. No live connection, approval actions or annotation storage. Every record remains semantically unverified until a person checks adequate evidence. Mechanical checks do not establish truth.</p></header>
<p><label>Find record <input id="search" placeholder="UUID or title"></label> <label>Filter <select id="filter"><option value="all">All approved records</option><option value="blocked">Fails strict collection gate</option><option value="automatic">Recorded automatic approval</option></select></label></p>
<p id="count" role="status"></p><main><nav id="list" aria-label="Approved records"></nav><section id="detail"></section></main>
<script type="application/json" id="cases">PAYLOAD</script><script>
const cases=JSON.parse(document.getElementById('cases').textContent);
const node=(tag,text,parent)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;parent.append(n);return n;};
function show(c){const area=document.getElementById('detail');area.replaceChildren();node('h2',c.record.title||c.record.listing_id,area);node('p',c.record.listing_id,area);node('h3','Verification findings',area);node('pre',JSON.stringify(c.check,null,2),area);node('h3','Frozen fields (unchanged)',area);const dl=node('dl',undefined,area);for(const [k,v] of Object.entries(c.record)){node('dt',k,dl);node('dd',v===null?'NULL':String(v),dl);}node('h3','Frozen product images',area);for(const image of c.images){const raw=image.storage_path.replaceAll('\\\\','/');if(!raw.startsWith('data/images/')||raw.includes('..')||raw.includes(':'))continue;const im=node('img',undefined,area);im.src='../backup/project/'+raw;im.alt='Product '+image.source_position;im.loading='lazy';}for(const [key,title] of [['ai_extractions','AI extraction history'],['review_actions','Quality-review actions'],['status_history','Collection-state history']]){const d=node('details',undefined,area);node('summary',title,d);node('pre',JSON.stringify(c[key],null,2),d);}}
function render(){const q=document.getElementById('search').value.toLowerCase(),f=document.getElementById('filter').value;const filtered=cases.filter(c=>(c.record.listing_id+' '+c.record.title).toLowerCase().includes(q)&&(f!=='blocked'||!c.check.strict_collection_gate_pass)&&(f!=='automatic'||c.check.automatic_approval_recorded));const list=document.getElementById('list');list.replaceChildren();document.getElementById('count').textContent=filtered.length+' / '+cases.length+' approved records';for(const c of filtered){const b=node('button',c.record.title||c.record.listing_id,list);b.onclick=()=>show(c);}if(filtered.length)show(filtered[0]);else document.getElementById('detail').replaceChildren();}
const drawRecord=show;
show=function(c){drawRecord(c);const area=document.getElementById('detail');node('h3','Remaining private source evidence',area);for(const field of ['screenshot_path','seller_screenshot_path','staging_text_path']){if(!c.check.private_evidence_available[field])continue;const raw=String(c.record[field]).replaceAll('\\\\','/');if(!raw.startsWith('data/private/')||raw.includes('..')||raw.includes(':'))continue;const a=node('a',field,area);a.href='../backup/project/'+raw.split('/').map(encodeURIComponent).join('/');a.target='_blank';a.rel='noopener';node('br',undefined,area);}};
document.getElementById('search').oninput=render;document.getElementById('filter').onchange=render;render();</script></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(page.replace("PAYLOAD", payload))
