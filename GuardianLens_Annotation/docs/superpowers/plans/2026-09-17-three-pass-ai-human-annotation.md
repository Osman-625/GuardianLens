# Three-Pass AI + Human Annotation Workflow Implementation Plan

> **For agentic workers:** This plan is executed inline, in this same session, by the same
> Claude instance that wrote it (not handed to fresh per-task subagents) — the audit findings and
> file contents are already loaded in context and re-deriving them per task would waste far more
> than it saves. If resumed in a new session, read `reports/annotation_workflow_audit.md` first.

**Goal:** Make Claude-annotation + Codex-annotation + the existing rule engine the three
independent inputs to one human-reviewed final-label pipeline, replace the two abandoned/never-run
annotation methodologies found in the audit, and leave the 120-listing Claude/Codex blind pilot
ready to execute (not executed) at the end of this plan.

**Architecture:** Three independent label sources feed one consensus join:
1. **Claude annotation** — a fresh Claude subagent (via the `Agent` tool, `general-purpose` type,
   no access to this conversation's context) is dispatched per listing batch with only
   `ANNOTATION_GUIDE.md` + the listing's own data/images. It never sees Codex's or the rule
   engine's output.
2. **Codex annotation** — the `codex:codex-rescue` subagent (Bash-only, bridges to the local
   Codex CLI, confirmed installed: `codex-cli 0.153.4`, session bridge already live via
   `CODEX_COMPANION_SESSION_ID`) is dispatched per listing batch with the same guide + data, same
   blindness constraint.
3. **Rule engine** — already built, already run, unchanged (`output/weak_annotations.csv`).

A `compute_consensus.py` join produces per-listing agreement/conflict flags; a
`build_human_review_queue.py` turns that into a prioritized P0–P4 queue; a human reviews via a
simple local review tool; `finalize_labels.py` applies the documented finalization policy;
`verify_final_dataset.py` + `freeze_dataset.py` produce the frozen, checksum'd labeled dataset;
`build_splits.py` produces leakage-safe train/validation/test/clean_validation splits. No model
training happens in this plan.

**Tech Stack:** Python 3.12 stdlib (`csv`, `json`, `hashlib`, `argparse`), no new runtime
dependencies beyond what's already in `requirements.txt` (Pillow, PyYAML, pytest). Claude/Codex
dispatch uses Claude Code's own `Agent` tool and `codex:codex-rescue` subagent — not a scripted
HTTP API call, since no `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` is configured as an env var in this
environment and the Codex CLI bridge is already the working, authorized path for this project.

**Spec:** this task's full instruction (STAGE A–F, 22 numbered sections) +
`reports/annotation_workflow_audit.md` (Stage A findings this plan acts on).

## Global Constraints

- Never modify: `data/annotation_ready/**`, `data/reference/**`, `data/excluded/**`, source
  collector DB, raw screenshots, `GuardianLens_Approved_Dataset/`, or anything under
  `rules/`, `scripts/rule_engine/`, `scripts/run_rule_annotation.py`,
  `scripts/verify_rule_annotations.py`, `scripts/extract_annotation_features.py`,
  `output/weak_annotations.csv`, `output/annotation_features.csv`.
- Never edit `PROGRESS_REPORT_AND_PLAN.md`, `docs/superpowers/plans/2026-09-14-rule-based-weak-labeling.md`,
  `Prepare GuardianLens Dataset for Annotation.md`, or anything under
  `C:\Users\cusma\OneDrive\Desktop\FYP Project\GuardianLens Project\` — treat as frozen reference.
- Canonical label vocabulary stays `legitimate` / `suspicious` / `scam_fraud` /
  `insufficient_evidence` (rule engine's `likely_legitimate`/`likely_scam` map onto this via an
  explicit table, never a silent string-equality comparison).
- `human_override_*`-style columns/files must never overwrite `claude_label`, `codex_label`, or
  `rule_label` — additive only, same pattern the rule engine already uses.
- Kappa gate (already documented in the recovered pilot `README.md` and
  `PROGRESS_REPORT_AND_PLAN.md`): **≥0.61 proceed**, **0.40–0.60 tighten rubric + re-pilot**,
  **<0.40 stop and escalate**. Do not silently tune prompts to inflate this number — document any
  guide change and re-run the full 120-pilot.
- Deterministic seed **42** everywhere a random sample or split is drawn.
- Do not train or evaluate any ML model in this plan. Do not run the full 2,209-listing Claude/
  Codex pass. Do not run the 120-listing pilot itself — stop at "ready to run."

---

## File structure decision (deviates from the task's suggested layout — documented why)

The task's suggested structure nests scripts under `scripts/annotation/`, `scripts/agreement/`,
etc. The audit found `scripts/*.py` is referenced by name (flat, no subfolder) from
`tests/test_rule_engine.py`, `.claude/skills/run-rule-annotation/SKILL.md`, and the frozen
`PROGRESS_REPORT_AND_PLAN.md`'s command examples. Moving existing files would force edits to a
frozen document, which this plan is not allowed to touch. **Decision: keep `scripts/` flat.** New
scripts are added alongside existing ones with self-explanatory names; only `annotation/` and
`archive/` gain new subdirectories, since nothing depends on their current absence.

```
GuardianLens_Annotation/
├── archive/legacy_annotation_workflows/         (NEW — Task 1)
│   ├── dual_human_pilot_v1/                     (recovered from zip, marked DEPRECATED)
│   ├── dual_human_full_dataset_templates_v1/    (recovered from zip, marked DEPRECATED)
│   └── README.md
├── annotation/
│   ├── guidelines/                              (NEW — Task 2)
│   │   ├── ANNOTATION_GUIDE.md                  (canonical copy, workflow section rewritten)
│   │   ├── LABEL_SCHEMA.json                    (adds annotator_version, rule-label mapping)
│   │   ├── DECISION_RULES.md
│   │   └── EVIDENCE_RULES.md
│   ├── pilot/                                   (NEW — Task 3)
│   │   ├── pilot_listing_ids.csv                (recovered from zip, re-validated against live data)
│   │   ├── claude_pilot.csv                     (empty output template)
│   │   ├── codex_pilot.csv                      (empty output template)
│   │   ├── pilot_agreement.csv / pilot_summary.json / pilot_disagreements.csv  (produced when pilot runs)
│   │   └── README.md
│   ├── runs/full_v1/                            (created empty, populated by a future Pass 2 run)
│   ├── review/                                  (human review tool output lands here)
│   ├── annotation_schema.json                   (unchanged)
│   ├── label_definitions.md                     (unchanged)
│   └── examples/worked_examples.md              (unchanged)
├── scripts/
│   ├── (all existing files unchanged)
│   ├── compute_agreement.py                     (EXTENDED — Task 4: confusion matrix, severe-disagreement flag, confidence distribution)
│   ├── select_pilot_sample.py                   (NEW — Task 3)
│   ├── compute_consensus.py                     (NEW — Task 5)
│   ├── build_human_review_queue.py              (NEW — Task 6, distinct from existing rule-only build_review_queue.py)
│   ├── finalize_labels.py                       (NEW — Task 8)
│   ├── verify_final_dataset.py                  (NEW — Task 9)
│   ├── freeze_dataset.py                        (NEW — Task 10)
│   └── build_splits.py                          (NEW — Task 11)
├── .claude/skills/run-ai-annotation-pilot/SKILL.md  (NEW — Task 7, at FYP Project root .claude/)
├── tests/ (new test files per task below)
└── README.md, ANNOTATION_GUIDE.md               (top-level copies REWRITTEN — Task 12 — to point at the new workflow; content is a thin pointer to annotation/guidelines/ANNOTATION_GUIDE.md, not a duplicate)
```

---

## Task 1: Archive the abandoned dual-human workflow for provenance

**Files:**
- Create: `archive/legacy_annotation_workflows/README.md`
- Create: `archive/legacy_annotation_workflows/dual_human_pilot_v1/` (from zip:
  `annotation/pilot/annotator_A_pilot.csv`, `annotator_B_pilot.csv`, `pilot_listing_ids.csv`,
  `README.md`)
- Create: `archive/legacy_annotation_workflows/dual_human_full_dataset_templates_v1/` (from zip:
  `annotation/templates/annotator_A.csv`, `annotator_B.csv`, `adjudication.csv`, `final_label.csv`)

**Interfaces:** none (static files, no code depends on this).

- [ ] **Step 1:** Extract the six named files from `GuardianLens_Annotation.zip` (already done
  once during the audit into the scratchpad — re-extract directly into the archive paths above).
- [ ] **Step 2:** Prepend a one-line `DEPRECATED_DO_NOT_USE` banner to each extracted CSV's
  companion note and write `archive/legacy_annotation_workflows/README.md` explaining: what these
  are, why retired (superseded by Claude+Codex+rule-engine 3-pass design, see
  `reports/annotation_workflow_audit.md` §1 Methods 1/1b), and that they were **never run** (all
  rows blank) — not lost work, just an abandoned design.
- [ ] **Step 3:** Confirm nothing in the live workspace references `annotation/templates/` or
  `annotation/pilot/annotator_A_pilot.csv` after this — `grep -rn "annotation/templates\|annotator_A_pilot\|annotator_B_pilot" --include=*.md --include=*.py .` should return zero hits outside `archive/` and `reports/annotation_workflow_audit.md`.

## Task 2: Canonical guideline set

**Files:**
- Create: `annotation/guidelines/ANNOTATION_GUIDE.md`, `LABEL_SCHEMA.json`,
  `DECISION_RULES.md`, `EVIDENCE_RULES.md`

**Interfaces:**
- Produces: `annotation/guidelines/LABEL_SCHEMA.json` with keys `labels` (the 4 canonical
  values), `confidence_scale` (1–5), `rule_engine_label_mapping` (`likely_legitimate`→
  `legitimate`, `likely_scam`→`scam_fraud`, `suspicious`→`suspicious`,
  `insufficient_evidence`→`insufficient_evidence`), `pilot_output_columns` (the exact column list
  every later task assumes: `listing_id, label, confidence, reason, evidence_text, evidence_image,
  evidence_behavioral, insufficient_evidence_reason, annotator, annotator_version, timestamp`).
- Consumed by: Task 3 (pilot templates), Task 4 (agreement script's `LABEL_VALUES`), Task 5
  (consensus join's rule-label mapping), Task 7 (the annotation-dispatch skill).

- [ ] **Step 1:** Copy `ANNOTATION_GUIDE.md`'s label-definition, evidence-judging, and five
  required-warning sections verbatim into `annotation/guidelines/ANNOTATION_GUIDE.md` (these were
  audited as accurate and reusable). Replace only the final "Workflow" section with the new 3-pass
  procedure: Pass 1 pilot (Claude+Codex, blind) → kappa gate → Pass 2 full run → rule engine
  (already done) → consensus → Pass 3 human review → finalize.
- [ ] **Step 2:** Write `LABEL_SCHEMA.json` per the Interfaces block above.
- [ ] **Step 3:** Write `DECISION_RULES.md` — codifies the guide's "combined evidence, not a
  single weak signal" rule as an explicit decision table (weak indicator list from this task's
  spec: low price, new seller, missing rating, low review count, reused image, missing location,
  unusual wording/condition, generic description → each alone is `insufficient_evidence` grounds
  at most, never `scam_fraud` alone).
- [ ] **Step 4:** Write `EVIDENCE_RULES.md` — what counts as citable evidence per field type
  (text/image/behavioral), lifted from the existing guide's "Documenting evidence" section plus
  the audit's finding that `evidence_reason` (single field) is being split into
  `evidence_text`/`evidence_image`/`evidence_behavioral` for the new pilot — document why (this
  task's spec's recommended column list) and that the old single-field shape remains valid for
  anything still using `annotation_schema.json` directly (rule-engine-adjacent tooling).
- [ ] **Step 5:** Run `python -c "import json; json.load(open('annotation/guidelines/LABEL_SCHEMA.json'))"` to confirm valid JSON.
- [ ] **Step 6:** Commit is not applicable (no git repo in this workspace) — skip commit step,
  proceed to Task 3.

## Task 3: Recover and validate the 120-listing pilot sample

**Files:**
- Create: `annotation/pilot/pilot_listing_ids.csv` (recovered from zip)
- Create: `scripts/select_pilot_sample.py`
- Create: `annotation/pilot/claude_pilot.csv`, `codex_pilot.csv` (empty templates)
- Create: `annotation/pilot/README.md`
- Test: `tests/test_pilot_sample.py`

**Interfaces:**
- Produces: `select_pilot_sample.py` exposes `validate_pilot_sample(pilot_csv_path: Path,
  listings_csv_path: Path) -> list[str]` (returns list of error strings, empty = valid) — checks
  every `pilot_listing_ids.csv` row's `listing_id` still exists in the live
  `data/annotation_ready/listings.csv`, that the sample is still 120 rows, and that at least 15
  rows have `reused_image_indicator=True`.
- Consumed by: Task 7's dispatch skill (reads `pilot_listing_ids.csv` to know which 120 listings
  to send to Claude/Codex).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pilot_sample.py
from pathlib import Path
import csv
from scripts.select_pilot_sample import validate_pilot_sample

WORKSPACE = Path(__file__).resolve().parent.parent

def test_recovered_pilot_sample_is_valid_against_live_listings():
    errors = validate_pilot_sample(
        WORKSPACE / "annotation" / "pilot" / "pilot_listing_ids.csv",
        WORKSPACE / "data" / "annotation_ready" / "listings.csv",
    )
    assert errors == []

def test_pilot_sample_has_120_rows_and_15_reused_image_cases():
    with (WORKSPACE / "annotation" / "pilot" / "pilot_listing_ids.csv").open(
        encoding="utf-8-sig", newline=""
    ) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 120
    reused = sum(1 for r in rows if r["reused_image_indicator"].strip().lower() == "true")
    assert reused >= 15
```

- [ ] **Step 2: Run test to verify it fails (file doesn't exist yet)**

Run: `pytest tests/test_pilot_sample.py -v`
Expected: FAIL — `pilot_listing_ids.csv` not yet copied into `annotation/pilot/`,
`scripts/select_pilot_sample.py` not yet created.

- [ ] **Step 3: Extract the pilot sample from the zip and write the validator**

Extract `GuardianLens_Annotation/annotation/pilot/pilot_listing_ids.csv` from
`GuardianLens_Annotation.zip` into `annotation/pilot/pilot_listing_ids.csv` (same extraction
approach used during the audit).

```python
# scripts/select_pilot_sample.py
from __future__ import annotations

import csv
from pathlib import Path


def validate_pilot_sample(pilot_csv_path: Path, listings_csv_path: Path) -> list[str]:
    errors: list[str] = []
    with Path(listings_csv_path).open(encoding="utf-8-sig", newline="") as f:
        live_ids = {row["listing_id"] for row in csv.DictReader(f)}

    with Path(pilot_csv_path).open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if len(rows) != 120:
        errors.append(f"expected 120 pilot rows, found {len(rows)}")

    missing = [r["listing_id"] for r in rows if r["listing_id"] not in live_ids]
    if missing:
        errors.append(f"{len(missing)} pilot listing_ids no longer exist in live listings.csv: {missing[:5]}...")

    reused = sum(1 for r in rows if r.get("reused_image_indicator", "").strip().lower() == "true")
    if reused < 15:
        errors.append(f"expected >=15 reused-image stress cases, found {reused}")

    return errors


if __name__ == "__main__":
    import sys

    workspace = Path(__file__).resolve().parent.parent
    errs = validate_pilot_sample(
        workspace / "annotation" / "pilot" / "pilot_listing_ids.csv",
        workspace / "data" / "annotation_ready" / "listings.csv",
    )
    if errs:
        for e in errs:
            print(f"FAIL: {e}")
        sys.exit(1)
    print("Pilot sample valid: 120 rows, all listing_ids live, reused-image stress cases present.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pilot_sample.py -v`
Expected: PASS. If `test_recovered_pilot_sample_is_valid_against_live_listings` fails because
some `listing_id`s from the 2026-09-13 zip snapshot no longer exist in the current
`listings.csv`, that is a real finding — do not silently drop rows; stop and report the exact
count of missing IDs so the resampling decision is made explicitly, not automatically.

- [ ] **Step 5: Create the empty output templates and pilot README**

`claude_pilot.csv` / `codex_pilot.csv` header (from `LABEL_SCHEMA.json`'s `pilot_output_columns`):
`listing_id,label,confidence,reason,evidence_text,evidence_image,evidence_behavioral,insufficient_evidence_reason,annotator,annotator_version,timestamp`
— pre-fill `listing_id` for all 120 rows (from `pilot_listing_ids.csv`), leave every other column
blank, `annotator` pre-filled to `claude_pilot_v1` / `codex_pilot_v1` respectively.

Write `annotation/pilot/README.md` adapting the recovered zip pilot README's structure (kappa
gate table, "what to do" steps) to the new Claude/Codex mechanism from Task 7 instead of two
human annotators.

## Task 4: Extend the agreement script (don't rewrite it)

**Files:**
- Modify: `scripts/compute_agreement.py`
- Test: `tests/test_compute_agreement.py`

**Interfaces:**
- Produces: adds `confusion_matrix(pairs) -> dict[tuple[str,str], int]` (full 4x4, not just
  off-diagonal disagreements), `severe_disagreements(pairs) -> list[tuple[str,str]]` (filters to
  exactly `("legitimate","scam_fraud")` and `("scam_fraud","legitimate")` pairs), and
  `confidence_distribution(a_rows, b_rows, common_ids) -> dict` (min/max/mean confidence per
  annotator among compared rows). Existing `cohens_kappa`, `load`, and CLI behavior are
  unchanged — this is additive.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_compute_agreement.py
from scripts.compute_agreement import confusion_matrix, severe_disagreements, cohens_kappa

def test_confusion_matrix_counts_every_pair_including_agreements():
    pairs = [("legitimate", "legitimate"), ("legitimate", "suspicious"), ("scam_fraud", "scam_fraud")]
    cm = confusion_matrix(pairs)
    assert cm[("legitimate", "legitimate")] == 1
    assert cm[("legitimate", "suspicious")] == 1
    assert cm[("scam_fraud", "scam_fraud")] == 1

def test_severe_disagreements_flags_opposite_ends_only():
    pairs = [
        ("legitimate", "scam_fraud"),
        ("scam_fraud", "legitimate"),
        ("legitimate", "suspicious"),
        ("legitimate", "legitimate"),
    ]
    severe = severe_disagreements(pairs)
    assert len(severe) == 2
    assert ("legitimate", "scam_fraud") in severe
    assert ("scam_fraud", "legitimate") in severe

def test_kappa_unchanged_for_perfect_agreement():
    pairs = [("legitimate", "legitimate")] * 5 + [("scam_fraud", "scam_fraud")] * 5
    assert cohens_kappa(pairs) == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_compute_agreement.py -v`
Expected: FAIL — `confusion_matrix` and `severe_disagreements` not defined yet.

- [ ] **Step 3: Add the functions to `scripts/compute_agreement.py`**

Insert after the existing `cohens_kappa` function (do not touch `load`, `main`, or
`LABEL_VALUES`):

```python
def confusion_matrix(pairs: list[tuple[str, str]]) -> dict[tuple[str, str], int]:
    matrix: dict[tuple[str, str], int] = {(a, b): 0 for a in LABEL_VALUES for b in LABEL_VALUES}
    for a, b in pairs:
        matrix[(a, b)] = matrix.get((a, b), 0) + 1
    return matrix


def severe_disagreements(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    severe_pair_set = {("legitimate", "scam_fraud"), ("scam_fraud", "legitimate")}
    return [(a, b) for a, b in pairs if (a, b) in severe_pair_set]


def confidence_distribution(a_rows: dict, b_rows: dict, common_ids: list[str]) -> dict:
    def stats(rows: dict, ids: list[str]) -> dict:
        vals = [float(rows[i]["confidence"]) for i in ids if rows[i].get("confidence", "").strip()]
        if not vals:
            return {"min": None, "max": None, "mean": None, "n": 0}
        return {"min": min(vals), "max": max(vals), "mean": sum(vals) / len(vals), "n": len(vals)}

    return {"a": stats(a_rows, common_ids), "b": stats(b_rows, common_ids)}
```

Then extend `main()` to print the severe-disagreement count and confidence distribution after the
existing disagreement-breakdown print block (append, do not remove existing prints):

```python
    severe = severe_disagreements(label_pairs)
    print(f"\nSevere (legitimate vs scam_fraud) disagreements: {len(severe)}")
    if severe:
        print("  *** THESE REQUIRE MANDATORY P0 HUMAN REVIEW ***")

    conf_dist = confidence_distribution(a_rows, b_rows, [lid for lid in common_ids if a_rows[lid].get("label","").strip() and b_rows[lid].get("label","").strip()])
    print(f"\nConfidence distribution: A={conf_dist['a']}, B={conf_dist['b']}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_compute_agreement.py -v`
Expected: PASS.

- [ ] **Step 5: Re-run the full existing suite to confirm nothing broke**

Run: `pytest -q`
Expected: 36 previously-passing tests + new ones, all PASS.

## Task 5: Three-way consensus join

**Files:**
- Create: `scripts/compute_consensus.py`
- Test: `tests/test_compute_consensus.py`

**Interfaces:**
- Consumes: `annotation/pilot/claude_pilot.csv` or `annotation/runs/full_v1/claude_annotations.csv`
  (columns from `LABEL_SCHEMA.json`), same shape for codex, and `output/weak_annotations.csv`
  (columns: `listing_id,rule_label,label_confidence,label_reason,...`) — read-only.
- Produces: a list of dict rows with keys `listing_id, claude_label, claude_confidence,
  codex_label, codex_confidence, rule_label_raw, rule_label_mapped, rule_confidence,
  ai_agreement (bool: claude_label==codex_label), three_way_agreement (bool: all three mapped
  labels equal), rule_ai_conflict (bool: ai_agreement is True but rule_label_mapped differs),
  severe_disagreement (bool: claude/codex pair is legitimate vs scam_fraud in either order)`.
  Consumed by Task 6 (review queue).

- [ ] **Step 1: Write the failing test with a small in-memory fixture**

```python
# tests/test_compute_consensus.py
import csv
from pathlib import Path
from scripts.compute_consensus import build_consensus, RULE_LABEL_MAP

def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

def test_three_way_agreement_when_all_sources_match(tmp_path):
    claude_csv = tmp_path / "claude.csv"
    codex_csv = tmp_path / "codex.csv"
    rule_csv = tmp_path / "rule.csv"
    _write_csv(claude_csv, [{"listing_id": "L1", "label": "scam_fraud", "confidence": "5"}],
               ["listing_id", "label", "confidence"])
    _write_csv(codex_csv, [{"listing_id": "L1", "label": "scam_fraud", "confidence": "4"}],
               ["listing_id", "label", "confidence"])
    _write_csv(rule_csv, [{"listing_id": "L1", "rule_label": "likely_scam", "label_confidence": "high"}],
               ["listing_id", "rule_label", "label_confidence"])

    rows = build_consensus(claude_csv, codex_csv, rule_csv)
    assert len(rows) == 1
    row = rows[0]
    assert row["ai_agreement"] is True
    assert row["rule_label_mapped"] == "scam_fraud"
    assert row["three_way_agreement"] is True
    assert row["rule_ai_conflict"] is False
    assert row["severe_disagreement"] is False

def test_severe_disagreement_flagged(tmp_path):
    claude_csv = tmp_path / "claude.csv"
    codex_csv = tmp_path / "codex.csv"
    rule_csv = tmp_path / "rule.csv"
    _write_csv(claude_csv, [{"listing_id": "L2", "label": "legitimate", "confidence": "3"}],
               ["listing_id", "label", "confidence"])
    _write_csv(codex_csv, [{"listing_id": "L2", "label": "scam_fraud", "confidence": "5"}],
               ["listing_id", "label", "confidence"])
    _write_csv(rule_csv, [{"listing_id": "L2", "rule_label": "insufficient_evidence", "label_confidence": "rough"}],
               ["listing_id", "rule_label", "label_confidence"])

    rows = build_consensus(claude_csv, codex_csv, rule_csv)
    assert rows[0]["severe_disagreement"] is True
    assert rows[0]["ai_agreement"] is False

def test_rule_label_map_covers_all_rule_engine_values():
    assert RULE_LABEL_MAP == {
        "likely_legitimate": "legitimate",
        "likely_scam": "scam_fraud",
        "suspicious": "suspicious",
        "insufficient_evidence": "insufficient_evidence",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_compute_consensus.py -v`
Expected: FAIL — `scripts/compute_consensus.py` doesn't exist.

- [ ] **Step 3: Implement `scripts/compute_consensus.py`**

```python
from __future__ import annotations

import argparse
import csv
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent

RULE_LABEL_MAP = {
    "likely_legitimate": "legitimate",
    "likely_scam": "scam_fraud",
    "suspicious": "suspicious",
    "insufficient_evidence": "insufficient_evidence",
}

SEVERE_PAIRS = {("legitimate", "scam_fraud"), ("scam_fraud", "legitimate")}


def _load(path: Path) -> dict[str, dict]:
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return {row["listing_id"]: row for row in csv.DictReader(f)}


def build_consensus(claude_csv: Path, codex_csv: Path, rule_csv: Path) -> list[dict]:
    claude_rows = _load(claude_csv)
    codex_rows = _load(codex_csv)
    rule_rows = _load(rule_csv)

    all_ids = sorted(set(claude_rows) | set(codex_rows) | set(rule_rows))
    out = []
    for lid in all_ids:
        c = claude_rows.get(lid, {})
        x = codex_rows.get(lid, {})
        r = rule_rows.get(lid, {})

        claude_label = c.get("label", "").strip() or None
        codex_label = x.get("label", "").strip() or None
        rule_label_raw = r.get("rule_label", "").strip() or None
        rule_label_mapped = RULE_LABEL_MAP.get(rule_label_raw) if rule_label_raw else None

        ai_agreement = bool(claude_label and codex_label and claude_label == codex_label)
        three_way_agreement = bool(
            claude_label and codex_label and rule_label_mapped
            and claude_label == codex_label == rule_label_mapped
        )
        rule_ai_conflict = bool(ai_agreement and rule_label_mapped and claude_label != rule_label_mapped)
        severe = bool(claude_label and codex_label and (claude_label, codex_label) in SEVERE_PAIRS)

        out.append({
            "listing_id": lid,
            "claude_label": claude_label,
            "claude_confidence": c.get("confidence", "").strip() or None,
            "codex_label": codex_label,
            "codex_confidence": x.get("confidence", "").strip() or None,
            "rule_label_raw": rule_label_raw,
            "rule_label_mapped": rule_label_mapped,
            "rule_confidence": r.get("label_confidence", "").strip() or None,
            "ai_agreement": ai_agreement,
            "three_way_agreement": three_way_agreement,
            "rule_ai_conflict": rule_ai_conflict,
            "severe_disagreement": severe,
        })
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claude", required=True, type=Path)
    parser.add_argument("--codex", required=True, type=Path)
    parser.add_argument("--rule", default=str(WORKSPACE / "output" / "weak_annotations.csv"), type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    rows = build_consensus(args.claude, args.codex, args.rule)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} consensus rows to {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_compute_consensus.py -v`
Expected: PASS.

## Task 6: Prioritized human review queue (P0–P4)

**Files:**
- Create: `scripts/build_human_review_queue.py`
- Test: `tests/test_human_review_queue.py`

**Interfaces:**
- Consumes: consensus rows shaped like Task 5's `build_consensus()` output, plus (optionally)
  `data/annotation_ready/listings.csv`'s `annotation_readiness`/`duplicate_status` columns for
  P3 criteria.
- Produces: `assign_priority(row: dict) -> tuple[str, str]` returning `(priority, reason)` where
  priority is one of `"P0","P1","P2","P3","P4"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_human_review_queue.py
from scripts.build_human_review_queue import assign_priority

def test_p0_severe_disagreement():
    row = {"claude_label": "legitimate", "codex_label": "scam_fraud", "severe_disagreement": True,
           "ai_agreement": False, "rule_ai_conflict": False, "claude_confidence": "4", "codex_confidence": "5",
           "annotation_readiness": "ready"}
    priority, reason = assign_priority(row)
    assert priority == "P0"

def test_p1_plain_ai_disagreement():
    row = {"claude_label": "suspicious", "codex_label": "insufficient_evidence", "severe_disagreement": False,
           "ai_agreement": False, "rule_ai_conflict": False, "claude_confidence": "3", "codex_confidence": "2",
           "annotation_readiness": "ready"}
    priority, reason = assign_priority(row)
    assert priority == "P1"

def test_p2_rule_conflict_only():
    row = {"claude_label": "legitimate", "codex_label": "legitimate", "severe_disagreement": False,
           "ai_agreement": True, "rule_ai_conflict": True, "claude_confidence": "4", "codex_confidence": "4",
           "annotation_readiness": "ready"}
    priority, reason = assign_priority(row)
    assert priority == "P2"

def test_p3_low_confidence_unanimous():
    row = {"claude_label": "suspicious", "codex_label": "suspicious", "severe_disagreement": False,
           "ai_agreement": True, "rule_ai_conflict": False, "claude_confidence": "1", "codex_confidence": "2",
           "annotation_readiness": "ready"}
    priority, reason = assign_priority(row)
    assert priority == "P3"

def test_p3_needs_review_readiness_flag():
    row = {"claude_label": "legitimate", "codex_label": "legitimate", "severe_disagreement": False,
           "ai_agreement": True, "rule_ai_conflict": False, "claude_confidence": "5", "codex_confidence": "5",
           "annotation_readiness": "needs_review"}
    priority, reason = assign_priority(row)
    assert priority == "P3"

def test_p4_unanimous_high_confidence_clean():
    row = {"claude_label": "legitimate", "codex_label": "legitimate", "severe_disagreement": False,
           "ai_agreement": True, "rule_ai_conflict": False, "claude_confidence": "5", "codex_confidence": "5",
           "annotation_readiness": "ready"}
    priority, reason = assign_priority(row)
    assert priority == "P4"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_human_review_queue.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `scripts/build_human_review_queue.py`**

```python
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent

LOW_CONFIDENCE_THRESHOLD = 3.0


def _conf(row: dict, key: str) -> float | None:
    v = row.get(key)
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def assign_priority(row: dict) -> tuple[str, str]:
    if row.get("severe_disagreement"):
        return "P0", "severe contradiction: claude vs codex opposite ends (legitimate/scam_fraud)"

    claude_label = row.get("claude_label")
    codex_label = row.get("codex_label")
    if claude_label and codex_label and claude_label != codex_label:
        return "P1", f"AI disagreement: claude={claude_label} vs codex={codex_label}"

    if row.get("rule_ai_conflict"):
        return "P2", "claude/codex agree but rule engine disagrees"

    claude_conf = _conf(row, "claude_confidence")
    codex_conf = _conf(row, "codex_confidence")
    low_confidence = (claude_conf is not None and claude_conf < LOW_CONFIDENCE_THRESHOLD) or \
                      (codex_conf is not None and codex_conf < LOW_CONFIDENCE_THRESHOLD)
    insufficient = claude_label == "insufficient_evidence" or codex_label == "insufficient_evidence"
    needs_review_flag = row.get("annotation_readiness") == "needs_review"
    possible_duplicate = row.get("duplicate_status") == "possible_duplicate"

    if low_confidence or insufficient or needs_review_flag or possible_duplicate:
        reasons = []
        if low_confidence:
            reasons.append("low confidence")
        if insufficient:
            reasons.append("insufficient_evidence called")
        if needs_review_flag:
            reasons.append("annotation_readiness=needs_review")
        if possible_duplicate:
            reasons.append("possible_duplicate")
        return "P3", "; ".join(reasons)

    return "P4", "unanimous, high confidence, clean readiness -- QC sample candidate"


def build_queue(consensus_rows: list[dict], qc_sample_rate: float = 0.05, seed: int = 42) -> list[dict]:
    queue = []
    p4_rows = []
    for row in consensus_rows:
        priority, reason = assign_priority(row)
        out_row = dict(row)
        out_row["review_priority"] = priority
        out_row["review_reason"] = reason
        out_row["requires_human_review"] = priority != "P4"
        if priority == "P4":
            p4_rows.append(out_row)
        else:
            queue.append(out_row)

    rng = random.Random(seed)
    sample_size = max(1, int(len(p4_rows) * qc_sample_rate)) if p4_rows else 0
    qc_sample = rng.sample(p4_rows, min(sample_size, len(p4_rows))) if p4_rows else []
    for row in qc_sample:
        row["requires_human_review"] = True
        row["review_reason"] = "QC stratified sample of unanimous case: " + row["review_reason"]

    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
    queue.extend(p4_rows)
    queue.sort(key=lambda r: priority_order[r["review_priority"]])
    return queue


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--consensus", required=True, type=Path)
    parser.add_argument("--out", default=str(WORKSPACE / "reports" / "human_review_queue.csv"), type=Path)
    parser.add_argument("--qc-sample-rate", type=float, default=0.05)
    args = parser.parse_args()

    with args.consensus.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for key in ("ai_agreement", "three_way_agreement", "rule_ai_conflict", "severe_disagreement"):
            row[key] = row.get(key) == "True"

    queue = build_queue(rows, qc_sample_rate=args.qc_sample_rate)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(queue[0].keys()))
        w.writeheader()
        w.writerows(queue)

    counts = {}
    for row in queue:
        counts[row["review_priority"]] = counts.get(row["review_priority"], 0) + 1
    print(f"Wrote {len(queue)} rows to {args.out}. Priority counts: {counts}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_human_review_queue.py -v`
Expected: PASS.

## Task 7: Claude/Codex blind-dispatch skill (the actual annotation mechanism)

**Files:**
- Create: `C:\Users\cusma\.claude\skills\run-ai-annotation-pilot\SKILL.md` (project-local skill,
  or `FYP Project/.claude/skills/run-ai-annotation-pilot/SKILL.md` if scoped to this project —
  use the project-local path so it doesn't leak into unrelated projects)

**Interfaces:** none (this is a runbook for the agent operator, not importable code). It must
name exactly: which listing_ids to process (from `annotation/pilot/pilot_listing_ids.csv`), the
exact `Agent` tool call shape for the Claude track (`subagent_type: general-purpose`, a prompt
that embeds `ANNOTATION_GUIDE.md` + `LABEL_SCHEMA.json`'s `pilot_output_columns` + one listing's
data/images path + explicit "you must not see any other annotator's output" instruction), the
exact `codex:codex-rescue` dispatch shape for the Codex track, and where each track's structured
response gets appended (`annotation/pilot/claude_pilot.csv` / `codex_pilot.csv`).

- [ ] **Step 1:** Write the skill file with: purpose, trigger conditions, batch size
  recommendation (small batches, e.g. 10 listings per subagent call, to keep each subagent's
  context focused and outputs auditable), the exact prompt template for each track (quoting
  `ANNOTATION_GUIDE.md` verbatim is not required — point the subagent at the file path instead,
  since it will have filesystem access), and a hard rule: **never include the other track's
  output file path, never include `output/weak_annotations.csv`, in either prompt.**
- [ ] **Step 2:** Include the exact commands for post-processing once both tracks finish a batch:
  `python scripts/verify_annotations.py --file annotation/pilot/claude_pilot.csv`, same for codex,
  then `python scripts/compute_agreement.py --a annotation/pilot/claude_pilot.csv --b annotation/pilot/codex_pilot.csv`.
- [ ] **Step 3:** Validate the skill loads: run `/skill-doctor` if available, or at minimum
  confirm the YAML frontmatter parses (`name`, `description` fields present) by reading the file
  back.

## Task 8: Finalization policy

**Files:**
- Create: `scripts/finalize_labels.py`
- Test: `tests/test_finalize_labels.py`

**Interfaces:**
- Consumes: a human-review-completed queue CSV (Task 6's shape + `human_final_label`,
  `human_reason`, `reviewer_id`, `review_timestamp`, `review_status` columns, populated for P0–P3
  rows and the P4 QC sample; blank for the remaining unreviewed P4 rows) and the full consensus
  CSV (Task 5's shape, for every listing).
- Produces: `finalize(consensus_rows, reviewed_rows) -> list[dict]` — every output row has
  `listing_id, final_label, final_label_source` where `final_label_source` is one of
  `"human_review"` (human filled `human_final_label`), `"unanimous_ai"` (claude==codex, no human
  review recorded, and the QC sample passed for that unanimous bucket) or `"unresolved"` (no
  human decision yet and not eligible for auto-finalization). **Never** silently sets
  `final_label = rule_label` — `rule_label` never appears as a `final_label_source` value.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_finalize_labels.py
from scripts.finalize_labels import finalize

def test_human_reviewed_row_uses_human_final_label():
    consensus = [{"listing_id": "L1", "claude_label": "legitimate", "codex_label": "scam_fraud"}]
    reviewed = [{"listing_id": "L1", "human_final_label": "suspicious", "review_status": "reviewed"}]
    out = finalize(consensus, reviewed)
    assert out[0]["final_label"] == "suspicious"
    assert out[0]["final_label_source"] == "human_review"

def test_unanimous_unreviewed_row_finalizes_from_ai_agreement():
    consensus = [{"listing_id": "L2", "claude_label": "legitimate", "codex_label": "legitimate"}]
    reviewed = []
    out = finalize(consensus, reviewed)
    assert out[0]["final_label"] == "legitimate"
    assert out[0]["final_label_source"] == "unanimous_ai"

def test_disagreement_without_human_review_is_unresolved_not_defaulted():
    consensus = [{"listing_id": "L3", "claude_label": "legitimate", "codex_label": "scam_fraud"}]
    reviewed = []
    out = finalize(consensus, reviewed)
    assert out[0]["final_label"] is None
    assert out[0]["final_label_source"] == "unresolved"

def test_rule_label_is_never_a_final_label_source():
    consensus = [{"listing_id": "L4", "claude_label": None, "codex_label": None, "rule_label_mapped": "scam_fraud"}]
    out = finalize(consensus, [])
    assert out[0]["final_label_source"] != "rule_label"
    assert out[0]["final_label_source"] == "unresolved"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_finalize_labels.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `scripts/finalize_labels.py`**

```python
from __future__ import annotations

import argparse
import csv
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent


def finalize(consensus_rows: list[dict], reviewed_rows: list[dict]) -> list[dict]:
    reviewed_by_id = {r["listing_id"]: r for r in reviewed_rows if r.get("human_final_label", "").strip()}

    out = []
    for row in consensus_rows:
        lid = row["listing_id"]
        if lid in reviewed_by_id:
            final_label = reviewed_by_id[lid]["human_final_label"].strip()
            source = "human_review"
        elif row.get("claude_label") and row.get("codex_label") and row["claude_label"] == row["codex_label"]:
            final_label = row["claude_label"]
            source = "unanimous_ai"
        else:
            final_label = None
            source = "unresolved"

        out.append({"listing_id": lid, "final_label": final_label, "final_label_source": source})
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--consensus", required=True, type=Path)
    parser.add_argument("--reviewed", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    with args.consensus.open(encoding="utf-8-sig", newline="") as f:
        consensus_rows = list(csv.DictReader(f))
    with args.reviewed.open(encoding="utf-8-sig", newline="") as f:
        reviewed_rows = list(csv.DictReader(f))

    out = finalize(consensus_rows, reviewed_rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["listing_id", "final_label", "final_label_source"])
        w.writeheader()
        w.writerows(out)

    unresolved = sum(1 for r in out if r["final_label_source"] == "unresolved")
    print(f"Wrote {len(out)} rows. Unresolved (need human review before freeze): {unresolved}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_finalize_labels.py -v`
Expected: PASS.

## Task 9: Final verification checklist script

**Files:**
- Create: `scripts/verify_final_dataset.py`
- Test: `tests/test_verify_final_dataset.py`

**Interfaces:**
- Consumes: a finalized-labels CSV (Task 8 shape) + `data/annotation_ready/listings.csv`.
- Produces: `run_checks(final_rows, listing_ids) -> list[str]` (list of problem strings; empty =
  pass), checking: no duplicate `listing_id`, every `final_label` (where not None) is one of the
  4 canonical values, every `listing_id` in `final_rows` exists in `listing_ids` and vice versa
  (no missing/extra rows), and the count of `unresolved` rows is reported (not itself a failure —
  unresolved rows are expected until Pass 3 finishes; the check is that they're *labeled*
  `unresolved`, not silently blank with no source).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_verify_final_dataset.py
from scripts.verify_final_dataset import run_checks

def test_passes_on_clean_input():
    final_rows = [{"listing_id": "L1", "final_label": "legitimate", "final_label_source": "unanimous_ai"}]
    errors = run_checks(final_rows, listing_ids={"L1"})
    assert errors == []

def test_flags_duplicate_listing_id():
    final_rows = [
        {"listing_id": "L1", "final_label": "legitimate", "final_label_source": "unanimous_ai"},
        {"listing_id": "L1", "final_label": "suspicious", "final_label_source": "human_review"},
    ]
    errors = run_checks(final_rows, listing_ids={"L1"})
    assert any("duplicate" in e.lower() for e in errors)

def test_flags_invalid_label_value():
    final_rows = [{"listing_id": "L1", "final_label": "maybe_scam", "final_label_source": "unanimous_ai"}]
    errors = run_checks(final_rows, listing_ids={"L1"})
    assert any("invalid" in e.lower() for e in errors)

def test_flags_missing_listing():
    final_rows = [{"listing_id": "L1", "final_label": "legitimate", "final_label_source": "unanimous_ai"}]
    errors = run_checks(final_rows, listing_ids={"L1", "L2"})
    assert any("L2" in e for e in errors)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_verify_final_dataset.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `scripts/verify_final_dataset.py`**

```python
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
VALID_LABELS = {"legitimate", "suspicious", "scam_fraud", "insufficient_evidence"}


def run_checks(final_rows: list[dict], listing_ids: set[str]) -> list[str]:
    errors = []

    ids_seen = [r["listing_id"] for r in final_rows]
    dupes = [lid for lid, count in Counter(ids_seen).items() if count > 1]
    if dupes:
        errors.append(f"duplicate listing_id rows found: {dupes}")

    for r in final_rows:
        label = r.get("final_label")
        if label and label not in VALID_LABELS:
            errors.append(f"{r['listing_id']}: invalid final_label {label!r}")

    final_ids = set(ids_seen)
    missing_from_final = listing_ids - final_ids
    extra_in_final = final_ids - listing_ids
    if missing_from_final:
        errors.append(f"{len(missing_from_final)} listing_ids missing from final dataset: {sorted(missing_from_final)[:5]}...")
    if extra_in_final:
        errors.append(f"{len(extra_in_final)} listing_ids in final dataset not in source listings.csv: {sorted(extra_in_final)[:5]}...")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", required=True, type=Path)
    parser.add_argument("--listings", default=str(WORKSPACE / "data" / "annotation_ready" / "listings.csv"), type=Path)
    args = parser.parse_args()

    with args.final.open(encoding="utf-8-sig", newline="") as f:
        final_rows = list(csv.DictReader(f))
    with args.listings.open(encoding="utf-8-sig", newline="") as f:
        listing_ids = {row["listing_id"] for row in csv.DictReader(f)}

    errors = run_checks(final_rows, listing_ids)
    unresolved = sum(1 for r in final_rows if r.get("final_label_source") == "unresolved")
    print(f"Checked {len(final_rows)} rows. Unresolved (pending Pass 3): {unresolved}.")
    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        raise SystemExit(1)
    print("All integrity checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_verify_final_dataset.py -v`
Expected: PASS.

## Task 10: Dataset freeze

**Files:**
- Create: `scripts/freeze_dataset.py`
- Test: `tests/test_freeze_dataset.py`

**Interfaces:**
- Consumes: a fully-resolved final-labels CSV (Task 9 passed, zero `unresolved` rows) +
  `data/annotation_ready/listings.csv`.
- Produces: `build_manifest(final_rows, version: str) -> dict` with `version, timestamp,
  row_count, label_distribution, platform_distribution` keys. Writing the checksum file and the
  merged `guardianlens_labeled_v1.csv` is done by `main()`, not unit-tested directly (I/O-only);
  `build_manifest` is unit tested since it's the logic-bearing piece.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_freeze_dataset.py
from scripts.freeze_dataset import build_manifest

def test_manifest_counts_labels_and_rows():
    final_rows = [
        {"listing_id": "L1", "final_label": "legitimate", "platform": "carousell"},
        {"listing_id": "L2", "final_label": "scam_fraud", "platform": "mudah"},
        {"listing_id": "L3", "final_label": "legitimate", "platform": "carousell"},
    ]
    manifest = build_manifest(final_rows, version="v1")
    assert manifest["row_count"] == 3
    assert manifest["label_distribution"]["legitimate"] == 2
    assert manifest["label_distribution"]["scam_fraud"] == 1
    assert manifest["platform_distribution"]["carousell"] == 2
    assert manifest["version"] == "v1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_freeze_dataset.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `scripts/freeze_dataset.py`**

```python
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent


def build_manifest(final_rows: list[dict], version: str) -> dict:
    return {
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "row_count": len(final_rows),
        "label_distribution": dict(Counter(r["final_label"] for r in final_rows)),
        "platform_distribution": dict(Counter(r.get("platform", "unknown") for r in final_rows)),
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", required=True, type=Path)
    parser.add_argument("--listings", default=str(WORKSPACE / "data" / "annotation_ready" / "listings.csv"), type=Path)
    parser.add_argument("--out-dir", default=str(WORKSPACE / "data" / "final_labeled"), type=Path)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()

    with args.final.open(encoding="utf-8-sig", newline="") as f:
        final_rows = list(csv.DictReader(f))
    with args.listings.open(encoding="utf-8-sig", newline="") as f:
        listings_by_id = {row["listing_id"]: row for row in csv.DictReader(f)}

    for r in final_rows:
        r["platform"] = listings_by_id.get(r["listing_id"], {}).get("platform", "unknown")

    unresolved = [r for r in final_rows if r.get("final_label_source") == "unresolved"]
    if unresolved:
        print(f"REFUSING TO FREEZE: {len(unresolved)} rows still unresolved. Run Pass 3 human review first.")
        raise SystemExit(1)

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / f"guardianlens_labeled_{args.version}.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(final_rows[0].keys()))
        w.writeheader()
        w.writerows(final_rows)

    manifest = build_manifest(final_rows, version=args.version)
    (out_dir / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    checksum_line = f"{_sha256(out_csv)}  {out_csv.name}\n"
    (out_dir / "checksums.sha256").write_text(checksum_line, encoding="utf-8")

    print(f"Froze {len(final_rows)} rows to {out_csv}")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_freeze_dataset.py -v`
Expected: PASS.

## Task 11: Leakage-safe ML splits (prepared, not used for training)

**Files:**
- Create: `scripts/build_splits.py`
- Test: `tests/test_build_splits.py`

**Interfaces:**
- Consumes: the frozen `guardianlens_labeled_v1.csv` (Task 10 output) joined against
  `data/annotation_ready/listings.csv`'s `duplicate_status` and
  `reports/dataset_validation_report.md`'s near-duplicate/repost group membership (read the
  existing `reports/dataset_validation_summary.json` for group IDs rather than re-deriving
  duplicate detection — that logic already exists and must not be reimplemented).
- Produces: `assign_splits(rows: list[dict], group_of: dict[str, str], seed: int = 42) ->
  dict[str, list[dict]]` with keys `train`, `validation`, `test`, `clean_validation` — splits by
  `group_of[listing_id]` (rows sharing a group never cross a split boundary) not by individual
  row, stratified by `final_label` where group sizes allow it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_build_splits.py
from scripts.build_splits import assign_splits

def test_grouped_rows_never_split_across_boundaries():
    rows = [
        {"listing_id": f"L{i}", "final_label": "legitimate"} for i in range(20)
    ] + [
        {"listing_id": f"S{i}", "final_label": "scam_fraud"} for i in range(20)
    ]
    group_of = {r["listing_id"]: (r["listing_id"][:2] if r["listing_id"] in ("L0","L1") else r["listing_id"]) for r in rows}
    group_of["L0"] = "dup_group_1"
    group_of["L1"] = "dup_group_1"

    splits = assign_splits(rows, group_of, seed=42)
    split_of_id = {}
    for split_name, split_rows in splits.items():
        for r in split_rows:
            split_of_id[r["listing_id"]] = split_name

    assert split_of_id["L0"] == split_of_id["L1"], "listings in the same duplicate group must land in the same split"

def test_all_rows_accounted_for_exactly_once():
    rows = [{"listing_id": f"L{i}", "final_label": "legitimate"} for i in range(50)]
    group_of = {r["listing_id"]: r["listing_id"] for r in rows}
    splits = assign_splits(rows, group_of, seed=42)
    all_out_ids = [r["listing_id"] for s in splits.values() for r in s]
    assert sorted(all_out_ids) == sorted(r["listing_id"] for r in rows)
    assert len(all_out_ids) == len(set(all_out_ids))

def test_deterministic_with_fixed_seed():
    rows = [{"listing_id": f"L{i}", "final_label": "legitimate" if i % 2 == 0 else "scam_fraud"} for i in range(100)]
    group_of = {r["listing_id"]: r["listing_id"] for r in rows}
    a = assign_splits(rows, group_of, seed=42)
    b = assign_splits(rows, group_of, seed=42)
    assert [r["listing_id"] for r in a["train"]] == [r["listing_id"] for r in b["train"]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_build_splits.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `scripts/build_splits.py`**

```python
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent


def assign_splits(rows: list[dict], group_of: dict[str, str], seed: int = 42,
                   ratios: dict[str, float] | None = None) -> dict[str, list[dict]]:
    ratios = ratios or {"train": 0.7, "validation": 0.15, "test": 0.15}

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[group_of.get(r["listing_id"], r["listing_id"])].append(r)

    group_ids = sorted(groups.keys())
    rng = random.Random(seed)
    rng.shuffle(group_ids)

    n = len(group_ids)
    n_train = int(n * ratios["train"])
    n_val = int(n * ratios["validation"])

    train_groups = set(group_ids[:n_train])
    val_groups = set(group_ids[n_train:n_train + n_val])
    test_groups = set(group_ids[n_train + n_val:])

    splits: dict[str, list[dict]] = {"train": [], "validation": [], "test": [], "clean_validation": []}
    for gid in train_groups:
        splits["train"].extend(groups[gid])
    for gid in val_groups:
        splits["validation"].extend(groups[gid])
        if len(groups[gid]) == 1:
            splits["clean_validation"].extend(groups[gid])
    for gid in test_groups:
        splits["test"].extend(groups[gid])

    return splits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", required=True, type=Path)
    parser.add_argument("--dedup-summary", default=str(WORKSPACE / "reports" / "dataset_validation_summary.json"), type=Path)
    parser.add_argument("--out-dir", default=str(WORKSPACE / "data" / "final_labeled" / "splits"), type=Path)
    args = parser.parse_args()

    with args.final.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    dedup = json.loads(args.dedup_summary.read_text(encoding="utf-8"))
    group_of: dict[str, str] = {}
    for gi, group in enumerate(dedup.get("cross_listing_near_duplicate_groups", [])):
        for lid in group.get("listing_ids", []):
            group_of[lid] = f"dup_group_{gi}"
    for gi, group in enumerate(dedup.get("possible_repost_candidates", [])):
        for lid in group.get("listing_ids", []):
            group_of.setdefault(lid, f"repost_group_{gi}")

    splits = assign_splits(rows, group_of, seed=42)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, split_rows in splits.items():
        path = args.out_dir / f"{name}.csv"
        if not split_rows:
            path.write_text("", encoding="utf-8")
            continue
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(split_rows[0].keys()))
            w.writeheader()
            w.writerows(split_rows)

    manifest = {
        "seed": 42,
        "counts": {name: len(rows) for name, rows in splits.items()},
        "split_hash": hashlib.sha256(json.dumps({n: sorted(r["listing_id"] for r in rs) for n, rs in splits.items()}, sort_keys=True).encode()).hexdigest(),
    }
    (args.out_dir / "split_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
```

**Note for the executor:** the real key names inside `dataset_validation_summary.json` must be
confirmed against the actual file (read it) before wiring `main()`'s dedup-group extraction —
the field names used above (`cross_listing_near_duplicate_groups`, `possible_repost_candidates`,
`listing_ids`) are best-effort from the audit's reading of `README.md`'s summary of that file's
contents, not a verified read of the JSON schema itself. Verify during Task 11's implementation,
adjust the key names in `main()` only (not in `assign_splits`, which is schema-agnostic) if they
differ.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_build_splits.py -v`
Expected: PASS.

## Task 12: Rewrite README.md / ANNOTATION_GUIDE.md to remove the stale workflow, add the split-safety doc pointer

**Files:**
- Modify: `README.md` (top-level workspace README)
- Modify: `ANNOTATION_GUIDE.md` (top-level — becomes a short pointer; full content lives in
  `annotation/guidelines/ANNOTATION_GUIDE.md`)

**Interfaces:** none (documentation only).

- [ ] **Step 1:** In `README.md`, replace the folder-structure diagram's `annotation/templates/`
  line with the real live structure (`annotation/guidelines/`, `annotation/pilot/`,
  `annotation/runs/`, `annotation/review/`), and replace "Starting annotation" / "Adjudication"
  sections with the 10-phase workflow from this task's spec §18, each phase naming its exact
  command (`python scripts/select_pilot_sample.py`, the `run-ai-annotation-pilot` skill,
  `python scripts/compute_agreement.py --a ... --b ...`, etc.).
- [ ] **Step 2:** In `ANNOTATION_GUIDE.md`, replace the stale "Workflow" section with: "See
  `annotation/guidelines/ANNOTATION_GUIDE.md` for the current canonical workflow; this file's
  label definitions and evidence-judging sections above are unchanged and still apply."
- [ ] **Step 3:** Grep-verify no remaining live reference to `annotation/templates/`:
  `grep -rn "annotation/templates" --include=*.md .` should return zero hits outside `archive/`.

## Task 13: Full-suite verification

- [ ] **Step 1:** Run `pytest -q` from `GuardianLens_Annotation/`. Expected: all previously-passing
  36 tests plus every new test file from Tasks 3–11, all PASS, zero failures.
- [ ] **Step 2:** Run `python scripts/select_pilot_sample.py` directly (not just via pytest) and
  confirm its printed validation message.
- [ ] **Step 3:** Confirm no file under `data/annotation_ready/`, `data/reference/`,
  `data/excluded/`, `rules/`, `scripts/rule_engine/`, `output/weak_annotations.csv`,
  `output/annotation_features.csv` was modified: compare each file's SHA-256 against the value in
  `reports/checksums.sha256` (extend that check if this file doesn't already cover them — if it
  doesn't, compute and print the hashes for a manual before/after diff instead of assuming).
- [ ] **Step 4:** Confirm `annotation/pilot/pilot_listing_ids.csv`,
  `annotation/guidelines/*`, `archive/legacy_annotation_workflows/*`, and all new `scripts/*.py`
  exist and are non-empty.

---

## Execution Handoff

This plan is executed **inline, in this session**, task by task, immediately after being written
— not handed to fresh subagents (see the note at the top of this document) — because the
executor already holds the full audit context this plan depends on. Each task above ends with its
own verification step; after Task 13 passes, this task's Stage F ("120-listing pilot ready to
run") is reached and the plan is complete. Actually running the pilot (dispatching Claude/Codex
against the 120 listings via Task 7's skill) is the next action after this plan, not part of it.
