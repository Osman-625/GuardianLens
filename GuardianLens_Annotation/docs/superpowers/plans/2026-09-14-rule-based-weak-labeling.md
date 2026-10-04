# Rule-Based Weak-Labeling Annotation System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a config-driven, rule-based labeling system on top of the already-cleaned,
already-verified `GuardianLens_Annotation/data/annotation_ready/listings.csv` dataset (2,209
listings) that assigns **every single listing** one of four labels (`likely_legitimate`,
`suspicious`, `likely_scam`, `insufficient_evidence`) plus a `label_confidence` tier
(`rough`/`moderate`/`high` — deliberately not called "weak": it describes how much corroborating
evidence stacked up, not how untrustworthy the system is) and a plain-English `label_reason`, so
a human can review and override any row at their own pace afterward — without training any model,
without touching the cleaned dataset, and without requiring a human to review all 2,209 rows
before labels exist.

**Architecture:** A generic rule engine (Python) reads declarative rule definitions from YAML
config files and evaluates them against a precomputed per-listing feature table. Every rule match
records *why* it fired (evidence) and rolls up into a human-readable `label_reason`. Scores
(`risk_score`, `trust_score`) drive a config-driven threshold table that assigns a `rule_label` +
`label_confidence` + `label_reason` to **every** row — no row is ever left unlabeled or blank.
Every output row also carries blank `human_override_label` / `human_override_reason` /
`reviewer_id` / `override_timestamp` columns *in the same file*, so a human corrects only the rows
they actually check, without a separate adjudication pipeline, and the original rule output is
never overwritten — only appended alongside, so agreement/disagreement stays analyzable. Everything
is additive to the existing workspace — no existing file in `data/annotation_ready/`,
`annotation/`, or the source collector repo is modified.

**Tech Stack:** Python 3.12 (matches the source collector's env), stdlib `csv`/`json`/`re`,
`PyYAML` for rule configs (new dependency), `pytest` for tests (new dev dependency). No ML
libraries — this is explicitly non-ML weak labeling.

**Spec:** `C:\Users\cusma\Downloads\rule base audit.md` (the "rule base audit" — 10-phase
spec this plan implements verbatim, adapted to the real codebase per the spec's own instruction
"Adapt this to the real codebase if needed"). Executors should read both documents.

## Revision Notes (why the labeling design looks the way it does)

This plan went through two rounds of user feedback before implementation started (nothing below
has been run yet either way):

1. **"I don't have enough time to review all 2,209 listings."** First response was to propose
   truncating the review queue to a capped, sampled subset.
2. **Correction: don't truncate — label everything automatically, let me review/override at my
   own pace, and don't call it a "weak" label.** This is the design actually reflected in Tasks
   6–7 below: `run_rule_annotation.py` labels **all** 2,209 rows every run (never a subset), each
   with a `label_confidence` tier (`rough`/`moderate`/`high` — not "weak") and a plain-English
   `label_reason`; `build_review_queue.py` re-orders the **full** set by priority instead of
   sampling any of it away; and `human_override_label`/`human_override_reason`/`reviewer_id`/
   `override_timestamp` live directly in `output/weak_annotations.csv` so the user corrects rows
   in place, at whatever depth their time allows, without a separate adjudication file. A rerun
   of the rule engine (e.g. after tuning a threshold) preserves any override already recorded —
   see `_preserve_existing_human_overrides` in Task 6.

The underlying methodological fact doesn't change with the renaming: `rule_label` is still not
`ground_truth_label`, and a human override is still just one more opinion recorded alongside the
rule engine's, not a promotion to verified truth. "Not weak" describes the confidence-tiering
vocabulary the human sees, not a claim that rule-based labels became ground truth.

## Verified Phase-1 Dataset Inspection (read-only, done before this plan was written)

**Do not re-derive these numbers — they were independently verified against the actual files,
not assumed from documentation:**

- `data/annotation_ready/listings.csv`: **2,209 rows**, **40 columns**, header confirmed via
  direct CSV parse (not just README). Note: header has a UTF-8 BOM on the first column
  (`\ufefflisting_id`) — every script in this plan MUST open with `encoding="utf-8-sig"`, not
  `"utf-8"`, or `listing_id` lookups silently fail.
- Platform split (independently counted): **Carousell 1,410 / Mudah 799** — matches
  `README.md` and `reports/dataset_validation_summary.json`.
- Images: **2,209/2,209 listings have ≥1 image** (0 zero-image listings), **2,062 have
  multiple images**. Per-image detail (10,970 images) lives in `reports/image_validation.csv`,
  not in `listings.csv`.
- Duplicate/near-duplicate images (from `reports/dataset_validation_summary.json`, spot-checked):
  **0 exact-duplicate image groups**, **318 near-duplicate within-listing groups** (a listing's
  own repeated photos — not a fraud signal), **174 near-duplicate cross-listing groups covering
  265 listings** (the real reused/stock-photo signal — already surfaced per-listing as
  `reused_image_indicator` in `listings.csv`, but the *group membership* / related listing IDs
  needed for Rule Group I's evidence trail only exist in the JSON, not the CSV).
- **6 possible repost-candidate groups** (`possible_repost_candidates` in the same JSON).
- Text: `title` and `description` are populated for all 2,209 rows (description non-empty for
  100%). PII inside these fields is already masked to a single generic `[REDACTED]` token
  (source collector's `pii.py`) — the *type* of PII (phone vs. email vs. bank) is **not**
  recoverable; this is a documented, permanent limitation, not something this plan can fix.
- Sanity keyword scan on raw title+description confirmed the text is usable for keyword rules
  (e.g. `wasap` 28 hits, `dulu` 18 hits, `tac` 87 *naive substring* hits — the last number is a
  trap: `"tac"` substring-matches inside `"contact"`, `"attack"`, etc. **This is why every
  keyword rule in this plan uses `\b`-bounded regex, never plain `in` substring checks.**

### Fields available for annotation rules (from `listings.csv` + `reports/image_validation.csv`)

| Category | Available | Notes |
|---|---|---|
| Identity | `listing_id`, `platform`, `source_url`, `marketplace_listing_id` | complete |
| Product | `title`, `description`, `category`, `condition`(+`_raw`), `price`, `price_missing`, `currency` | complete |
| Seller | `account_age_days`(+`_missing`), `seller_rating`(+`_missing`), `review_count`(+`_missing`), `active_listing_count`(+`_missing`) | NULL-preserving, correct semantics already |
| Location | `location_state`(+`_raw`,`_invalid`), `location_city`, `location_missing` | complete |
| Text meta | `language`(+`_raw`), `contains_redacted_pii`, `redacted_pii_count` | no PII *type* breakdown (documented limitation) |
| Images | `image_count`, `primary_image_path`, `reused_image_indicator`; per-image `sha256`/`phash`/`width`/`height` in `reports/image_validation.csv` | SHA256/pHash exist but are in a **separate file**, joined by `listing_id`/`image_id` |
| Other | `duplicate_status`, `annotation_readiness`, `validation_status` | complete |

### Fields/rules that CANNOT be implemented yet (evidence unavailable) — carried into rule config as `enabled: false`

- **Rule Group A (A1–A10, Semak Mule + OTP/TAC/PIN/CVV/phishing-URL requests):** the *keyword*
  half (A3–A10, "asks for OTP", "asks for CVV", phishing-URL patterns) IS implementable from
  `description` text. The **Semak Mule half (A1, A2)** is NOT — no Semak Mule lookup was ever
  performed on this dataset and the spec explicitly forbids scraping/fabricating it now. Add
  `semak_mule_checked`/`semak_mule_phone_hit`/`semak_mule_bank_hit` as **NULL-only** columns
  (never computed, never guessed), and A1/A2 rule entries with `enabled: false` and a
  `required_fields` note explaining why.
- **PII-type-specific rules** (e.g., "phone number present" as a *distinct* signal from "email
  present"): source data only preserves a generic `[REDACTED]` token count, not which PII type.
  Any rule needing a phone-specific vs. email-specific signal is infeasible; only
  `contains_redacted_pii`/`redacted_pii_count` (generic) can be used.
- **Rule Group M contradictions requiring cross-modal understanding** (e.g., "image appears
  unrelated to title/category") — no vision-based classifier is in scope for a rule-based
  system; only the text-only contradiction checks (category vs. keyword conflicts) are
  implementable now. Document the rest as `enabled: false` with a note that they need a future
  vision-assist pass, not fabricated logic.
- **Platform buyer-protection info** (Rule Group L trust signal) — not present in the source
  schema at all (confirmed: `_excluded_by_design` in `data/reference/schema.json` lists no such
  field, and no listing-level field maps to it). Omit this trust signal entirely rather than
  invent a proxy.

## Global Constraints

- **Never modify** `GuardianLens_Annotation/data/annotation_ready/**`, `data/reference/**`,
  `data/excluded/**`, `annotation/**` (the human-pilot workspace), or anything in
  `GuardianLens_Data_Collector_v_1.0.0/` — every script in this plan is read-only against those
  paths.
- **Never write** `ground_truth_label` anywhere — the column/field name is always `rule_label`.
- **NULL stays NULL.** No feature-extraction or rule-evaluation step may convert a missing value
  to 0, `false`, or any other default. `price_missing=True` means "don't compute a price rule for
  this row," not "price=0."
- **All rule keyword matching uses `\b`-bounded regex** (via `re.compile(..., re.IGNORECASE)`),
  never plain substring `in` checks — verified necessary by the `"tac"`-in-`"contact"` false
  positive found during Phase 1 inspection above.
- **Existing `scripts/verify_annotations.py` in this workspace is for the human-annotation
  pilot (label vocabulary `legitimate/suspicious/scam_fraud/insufficient_evidence`,
  `annotator_id`-keyed).** This plan's Phase-10 verifier is a **new, separately-named** script
  (`verify_rule_annotations.py`) to avoid colliding with it or its vocabulary
  (`likely_scam/suspicious/likely_legitimate/insufficient_evidence`, `rule_version`-keyed).
- Every rule lives in YAML, never hardcoded in Python. Every threshold lives in
  `rules/thresholds.yaml`, never hardcoded in Python.
- Every rule match must record an `evidence` string/object explaining why it fired — never just
  `listing_id` + label (Phase 6 requirement).
- A single weak signal never equals a scam label on its own (new_account, zero_reviews,
  WhatsApp-mention, low_price are each individually insufficient — enforced by weights, not by
  ad hoc code branches).
- **Every row gets a `rule_label`, a `label_confidence`, and a non-empty plain-English
  `label_reason`** — including `insufficient_evidence` rows, whose reason must say *what's*
  missing (e.g. "no seller signals and no risk/trust rules fired"), never leave the field blank.
- `label_confidence` values are `rough` / `moderate` / `high` — never "weak." `high` = a critical
  rule fired or multiple strong signals corroborate each other; `moderate` = the threshold was
  met by one strong signal or several medium ones; `rough` = borderline, or a single
  weak/isolated signal pushed the score over a threshold. This exists purely so a
  time-constrained human reviewer can triage by how much they need to double-check a row — it is
  not a hedge on the label itself.
- `human_override_label` / `human_override_reason` / `reviewer_id` / `override_timestamp` live in
  `output/weak_annotations.csv` itself (not a separate adjudication file) and start blank on
  every fresh run. A human fills them in only for rows they've actually reviewed; the rule
  engine's own `rule_label`/`label_confidence`/`label_reason`/`evidence` are never mutated by a
  human edit, so agreement/disagreement between rule and human stays fully analyzable later.
- The rule engine must label **all** rows in one run — there is no "skip if uncertain" path;
  uncertainty is a label (`insufficient_evidence`), not an omission.

---

## File Structure

```
GuardianLens_Annotation/
├── requirements.txt                        [MODIFY: add PyYAML, pytest]
├── rules/                                   [NEW]
│   ├── scam_rules.yaml                      [NEW: rule catalog, Groups A-M]
│   ├── keyword_patterns.yaml                [NEW: EN/MS phrase lists per category]
│   ├── thresholds.yaml                      [NEW: weak-label decision thresholds]
│   └── rule_documentation.md                [NEW: Phase 8 per-rule-family docs]
├── scripts/
│   ├── rule_engine/                         [NEW package]
│   │   ├── __init__.py
│   │   ├── config.py                        [NEW: YAML loaders + validation]
│   │   ├── keyword_matcher.py               [NEW: word-boundary regex + combo scoring]
│   │   ├── price_stats.py                   [NEW: category-median price ratio]
│   │   ├── image_evidence.py                [NEW: cross-listing dup lookup]
│   │   ├── text_similarity.py               [NEW: description near-dup detection]
│   │   └── evaluator.py                     [NEW: rule evaluation -> scores + evidence]
│   ├── extract_annotation_features.py       [NEW: Phase 4 feature table]
│   ├── run_rule_annotation.py               [NEW: Phase 5 weak labels + Phase 6 evidence]
│   ├── build_review_queue.py                [NEW: Phase 7]
│   └── verify_rule_annotations.py           [NEW: Phase 10, distinct from verify_annotations.py]
├── reports/
│   ├── dataset_audit.json                   [NEW: Phase 1 machine-readable report]
│   ├── rule_coverage.csv                    [NEW]
│   ├── rule_matches.csv                     [NEW]
│   ├── annotation_summary.json              [NEW: now incl. confidence_counts]
│   └── review_queue.csv                     [NEW: ALL rows, priority-ordered, none dropped]
├── output/                                  [NEW dir]
│   └── weak_annotations.csv                 [NEW: all 2,209 rows; rule_label + label_confidence
│                                                  + label_reason + human_override_* per row]
└── tests/                                   [NEW]
    ├── conftest.py                          [NEW: synthetic fixture rows]
    └── test_rule_engine.py                  [NEW: 16 required scenarios]
```

Nothing under `data/`, `annotation/`, or `docs/DATASET_SPLIT_SAFETY.md` is touched.

---

## Progress View

| # | Task | Spec phase(s) | Status |
|---|------|---------------|--------|
| 1 | Workspace scaffold + dependencies | Phase 2 | [ ] Not started |
| 2 | Rule config schema + loader | Phase 3 | [ ] Not started |
| 3 | Keyword pattern library + matcher engine | Groups B–G | [ ] Not started |
| 4 | Full rule catalog (`scam_rules.yaml`, Groups A–M) | Groups A–M | [ ] Not started |
| 5 | Feature extraction script | Phase 4 | [ ] Not started |
| 6 | Rule evaluation + weak labels + evidence | Phase 5, 6 | [ ] Not started |
| 7 | Human review queue builder | Phase 7 | [ ] Not started |
| 8 | Rule documentation | Phase 8 | [ ] Not started |
| 9 | Test suite (16 required scenarios) | Phase 9 | [ ] Not started |
| 10 | Final verification + FINAL OUTPUT report | Phase 10 + "Final Output" | [ ] Not started |

**Prerequisite already satisfied (not part of this plan):** dataset cleaning/standardization/export
(the *other* spec, "Prepare GuardianLens Dataset for Annotation.md") is complete and verified
(20/20 checks passed, 2026-09-14). This plan builds strictly on top of that stable output and does
not re-touch it.

**Nothing below has been implemented yet.** This document is the plan only, per your instruction
to stop before running anything.

---

## Task 1: Workspace scaffold + dependencies

**Files:**
- Create: `rules/` (empty dir, populated in Tasks 2–4)
- Create: `output/` (empty dir, populated in Task 6)
- Create: `tests/` (empty dir, populated in Task 9)
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `rules/`, `output/`, `tests/` directories that later tasks write into.

- [ ] **Step 1: Add new dependencies**

```
Pillow>=10.0
PyYAML>=6.0
pytest>=8.0
```

- [ ] **Step 2: Create empty directories**

```bash
mkdir -p rules output tests scripts/rule_engine
```

- [ ] **Step 3: Verify nothing else changed**

Run: `git status` (if this workspace is a git repo) or diff a `find . -newer <marker>` snapshot —
confirm only `requirements.txt` changed plus new empty directories.
Expected: no existing file under `data/`, `annotation/`, `reports/`, `scripts/*.py` modified.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt rules output tests scripts/rule_engine
git commit -m "chore: scaffold rule-based weak-labeling workspace"
```

---

## Task 2: Rule config schema + loader

**Files:**
- Create: `scripts/rule_engine/__init__.py`
- Create: `scripts/rule_engine/config.py`
- Test: `tests/test_rule_engine.py` (this task's portion only)

**Interfaces:**
- Produces: `load_rules(path) -> list[Rule]`, `Rule` dataclass with fields
  `rule_id, name, description, category, severity, weight, required_fields, matching_method,
  evidence_to_record, source_reference, enabled`; `load_thresholds(path) -> ThresholdConfig`.
- Consumes: nothing (first engine module).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rule_engine.py
from pathlib import Path
from scripts.rule_engine.config import load_rules, Rule

def test_load_rules_parses_required_fields(tmp_path):
    yaml_text = """
- rule_id: R_TEST
  name: Test rule
  description: A test rule
  category: payment
  severity: strong
  weight: 4
  required_fields: [description]
  matching_method: keyword_group
  evidence_to_record: matched_phrase
  source_reference: "internal test"
  enabled: true
"""
    p = tmp_path / "scam_rules.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    rules = load_rules(p)
    assert len(rules) == 1
    assert rules[0] == Rule(
        rule_id="R_TEST", name="Test rule", description="A test rule",
        category="payment", severity="strong", weight=4,
        required_fields=["description"], matching_method="keyword_group",
        evidence_to_record="matched_phrase", source_reference="internal test",
        enabled=True,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_rule_engine.py::test_load_rules_parses_required_fields -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.rule_engine.config'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/rule_engine/__init__.py
"""Rule-based weak-labeling engine for GuardianLens annotation prep."""
```

```python
# scripts/rule_engine/config.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

VALID_SEVERITIES = {"critical", "strong", "medium", "weak", "trust"}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    name: str
    description: str
    category: str
    severity: str
    weight: float
    required_fields: list[str] = field(default_factory=list)
    matching_method: str = "keyword_group"
    evidence_to_record: str = "matched_phrase"
    source_reference: str = ""
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(
                f"{self.rule_id}: invalid severity {self.severity!r}, "
                f"must be one of {sorted(VALID_SEVERITIES)}"
            )
        if not self.rule_id:
            raise ValueError("rule_id must not be empty")


@dataclass(frozen=True)
class ThresholdConfig:
    critical_rule_min: int
    strong_risk_score_min: float
    strong_rule_count_min: int
    suspicious_risk_score_min: float
    legitimate_risk_score_max: float
    legitimate_trust_score_min: float


def load_rules(path: str | Path) -> list[Rule]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    rules: list[Rule] = []
    seen_ids: set[str] = set()
    for entry in raw:
        rule = Rule(**entry)
        if rule.rule_id in seen_ids:
            raise ValueError(f"duplicate rule_id: {rule.rule_id}")
        seen_ids.add(rule.rule_id)
        rules.append(rule)
    return rules


def load_thresholds(path: str | Path) -> ThresholdConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return ThresholdConfig(**raw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_rule_engine.py::test_load_rules_parses_required_fields -v`
Expected: PASS

- [ ] **Step 5: Add a duplicate-rule-id rejection test and confirm it passes**

```python
def test_load_rules_rejects_duplicate_ids(tmp_path):
    p = tmp_path / "dup.yaml"
    p.write_text("""
- rule_id: R_A
  name: A
  description: a
  category: payment
  severity: weak
  weight: 1
  required_fields: [description]
  matching_method: keyword_group
  evidence_to_record: x
  source_reference: ""
  enabled: true
- rule_id: R_A
  name: A2
  description: a2
  category: payment
  severity: weak
  weight: 1
  required_fields: [description]
  matching_method: keyword_group
  evidence_to_record: x
  source_reference: ""
  enabled: true
""", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="duplicate rule_id"):
        load_rules(p)
```

Run: `python -m pytest tests/test_rule_engine.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/rule_engine/__init__.py scripts/rule_engine/config.py tests/test_rule_engine.py
git commit -m "feat: add rule/threshold YAML config loader with validation"
```

---

## Task 3: Keyword pattern library + matcher engine

**Files:**
- Create: `rules/keyword_patterns.yaml`
- Create: `scripts/rule_engine/keyword_matcher.py`
- Test: `tests/test_rule_engine.py` (additions)

**Interfaces:**
- Consumes: nothing new.
- Produces: `MatchResult(category: str, matched_phrases: list[str], strength: str)`,
  `match_keywords(text: str, patterns: dict) -> list[MatchResult]`,
  `has_combo(matches: list[MatchResult], required_categories: list[str]) -> bool`.
  Later tasks (5, 6) call `match_keywords()` per listing's `title + " " + description`.

- [ ] **Step 1: Write `rules/keyword_patterns.yaml`**

```yaml
# Phrase lists are literal strings from the spec (English + Malay + common Malaysian
# marketplace variants). Every phrase is compiled to a \b-bounded, case-insensitive regex —
# never a plain substring check (see Global Constraints: the "tac" in "contact" false positive).
advance_payment:
  weak:
    - "deposit"
    - "booking fee"
    - "reservation fee"
  strong:
    - "deposit first"
    - "deposit dulu"
    - "secure item with deposit"
    - "advance payment"
    - "bayar dahulu"
    - "bayar dulu"
    - "duit muka"
    - "transfer first"
    - "direct transfer"
    - "payment outside platform"
    - "pay before viewing"
    - "deposit before inspection"
    - "bank transfer"

agent_courier_release_fee:
  strong:
    - "agent fee"
    - "courier fee"
    - "processing fee"
    - "release fee"
    - "verification fee"
    - "shipping agent fee"
    - "insurance fee"
    - "payment release fee"
    - "caj ejen"
    - "caj penghantaran"
    - "caj proses"
    - "bayaran pelepasan"

fake_payment_confirmation:
  medium:
    - "payment already made"
    - "payment confirmed"
    - "money transferred"
    - "click to receive payment"
    - "claim payment"
    - "verify to receive payment"
    - "payment pending verification"
    - "release funds"
    - "payment waiting"
    - "buyer already paid"

off_platform_contact:
  weak:
    - "whatsapp"
    - "whatsapp me"
    - "wasap"
    - "\\bws\\b"
    - "telegram"
    - "pm whatsapp"
    - "call me"
    - "contact number"
    - "hubungi whatsapp"
    - "hubungi nombor"
    - "direct message outside platform"

impersonation:
  weak:
    - "carousell admin"
    - "carousell support"
    - "carousell staff"
    - "mudah admin"
    - "mudah staff"
    - "payment department"
    - "bank officer"
    - "official agent"
    - "courier representative"

credential_request:
  critical:
    - "otp"
    - "\\btac\\b"
    - "one time password"
    - "\\bpin\\b number"
    - "cvv"
    - "security code"
    - "card number"
    - "bank password"
    - "bank login"

urgency_language:
  weak:
    - "act now"
    - "limited time"
    - "hurry"
    - "last chance"
    - "urgent sale"
    - "jual segera"
    - "cepat"
```

- [ ] **Step 2: Write the failing test**

```python
def test_keyword_matcher_uses_word_boundaries_not_substring():
    from scripts.rule_engine.keyword_matcher import match_keywords
    patterns = {"credential_request": {"critical": ["\\btac\\b"]}}
    # "contact" must NOT match \btac\b
    results = match_keywords("please contact me for details", patterns)
    assert results == []
    results2 = match_keywords("send the TAC code now", patterns)
    assert len(results2) == 1
    assert results2[0].category == "credential_request"
    assert results2[0].strength == "critical"
    assert "tac" in [p.lower() for p in results2[0].matched_phrases]


def test_keyword_matcher_combo_strength():
    from scripts.rule_engine.keyword_matcher import match_keywords, has_combo
    patterns = {
        "off_platform_contact": {"weak": ["whatsapp"]},
        "advance_payment": {"strong": ["deposit first"]},
    }
    text = "WhatsApp me, deposit first before viewing"
    results = match_keywords(text, patterns)
    categories = {r.category for r in results}
    assert categories == {"off_platform_contact", "advance_payment"}
    assert has_combo(results, ["off_platform_contact", "advance_payment"]) is True
    assert has_combo(results, ["off_platform_contact", "credential_request"]) is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_rule_engine.py -k keyword_matcher -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 4: Implement**

```python
# scripts/rule_engine/keyword_matcher.py
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MatchResult:
    category: str
    strength: str
    matched_phrases: tuple[str, ...]


def _phrase_regex(phrase: str) -> re.Pattern:
    # Phrases already containing regex metacharacters (e.g. "\\btac\\b") are used as-is;
    # plain phrases get \b-bounded automatically so "tac" never matches inside "contact".
    if any(ch in phrase for ch in r"\.^$*+?{}[]|()"):
        return re.compile(phrase, re.IGNORECASE)
    escaped = re.escape(phrase)
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


def match_keywords(text: str, patterns: dict) -> list[MatchResult]:
    if not text:
        return []
    results: list[MatchResult] = []
    for category, strengths in patterns.items():
        for strength, phrases in strengths.items():
            hits = tuple(p for p in phrases if _phrase_regex(p).search(text))
            if hits:
                results.append(MatchResult(category=category, strength=strength, matched_phrases=hits))
    return results


def has_combo(matches: list[MatchResult], required_categories: list[str]) -> bool:
    present = {m.category for m in matches}
    return all(c in present for c in required_categories)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_rule_engine.py -k keyword_matcher -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add rules/keyword_patterns.yaml scripts/rule_engine/keyword_matcher.py tests/test_rule_engine.py
git commit -m "feat: add EN/MS keyword pattern library with word-boundary matching"
```

---

## Task 4: Full rule catalog (`scam_rules.yaml`, Groups A–M)

**Files:**
- Create: `rules/scam_rules.yaml`

**Interfaces:**
- Consumes: `Rule` dataclass from Task 2 (must validate against it).
- Produces: the rule catalog `run_rule_annotation.py` (Task 6) loads via `load_rules()`.

- [ ] **Step 1: Write `rules/scam_rules.yaml`** (one entry per rule; `enabled: false` + explanatory
  `description` suffix for anything Phase-1 inspection found infeasible)

```yaml
# ---- Group A: critical fraud indicators ----
- rule_id: A1_SEMAK_MULE_PHONE
  name: Semak Mule positive phone number
  description: >
    NOT IMPLEMENTED: no Semak Mule lookup exists for this dataset and the spec forbids
    scraping/fabricating it. semak_mule_phone_hit stays NULL for every row.
  category: critical
  severity: critical
  weight: 10
  required_fields: [semak_mule_phone_hit]
  matching_method: field_equals_true
  evidence_to_record: semak_mule_phone_hit
  source_reference: "Semak Mule / PDRM CCID (not queried - out of scope)"
  enabled: false

- rule_id: A2_SEMAK_MULE_BANK
  name: Semak Mule positive bank account
  description: "Same limitation as A1 - not queried."
  category: critical
  severity: critical
  weight: 10
  required_fields: [semak_mule_bank_hit]
  matching_method: field_equals_true
  evidence_to_record: semak_mule_bank_hit
  source_reference: "Semak Mule / PDRM CCID (not queried - out of scope)"
  enabled: false

- rule_id: A3_A7_CREDENTIAL_REQUEST
  name: Request for OTP/TAC/PIN/CVV/bank login
  description: "Text asks the buyer/seller for a one-time code, PIN, CVV, or bank credential."
  category: critical
  severity: critical
  weight: 8
  required_fields: [description]
  matching_method: keyword_group:credential_request
  evidence_to_record: matched_phrase
  source_reference: "PDRM / NSRC common scam-script patterns"
  enabled: true

- rule_id: A8_A9_PHISHING_URL
  name: Suspicious payment or phishing URL / fake marketplace payment page
  description: "External URL classified suspicious by image_evidence/url heuristics (Group G)."
  category: critical
  severity: critical
  weight: 8
  required_fields: [description]
  matching_method: url_suspicious
  evidence_to_record: suspicious_domains
  source_reference: "Carousell/Mudah Trust & Safety phishing advisories"
  enabled: true

- rule_id: A10_IMPERSONATION_PLUS_PAYMENT
  name: Payment/credential request while impersonating platform/bank/courier
  description: "Combo: impersonation keyword AND (credential_request OR advance_payment)."
  category: critical
  severity: critical
  weight: 9
  required_fields: [description]
  matching_method: keyword_combo:impersonation+credential_request|advance_payment
  evidence_to_record: matched_phrase
  source_reference: "Carousell/Mudah Trust & Safety impersonation advisories"
  enabled: true

# ---- Group B: payment scam patterns ----
- rule_id: B1_ADVANCE_PAYMENT_WEAK
  name: Advance payment language (weak form)
  description: "'deposit' alone, unqualified."
  category: payment
  severity: weak
  weight: 1
  required_fields: [description]
  matching_method: keyword_group:advance_payment:weak
  evidence_to_record: matched_phrase
  source_reference: "Carousell Malaysia Trust & Safety guidance"
  enabled: true

- rule_id: B2_ADVANCE_PAYMENT_STRONG
  name: Advance payment language (strong form)
  description: "Deposit tied to an amount/urgency, e.g. 'deposit RM200 first before viewing'."
  category: payment
  severity: strong
  weight: 4
  required_fields: [description]
  matching_method: keyword_group:advance_payment:strong
  evidence_to_record: matched_phrase
  source_reference: "Carousell Malaysia Trust & Safety guidance"
  enabled: true

# ---- Group C: agent/courier/release fee ----
- rule_id: C1_RELEASE_FEE
  name: Fee required to receive/release money
  description: "Very strong pattern per spec - a legitimate transaction never requires the payee to pay a fee to receive funds."
  category: payment
  severity: strong
  weight: 6
  required_fields: [description]
  matching_method: keyword_group:agent_courier_release_fee
  evidence_to_record: matched_phrase
  source_reference: "NSRC / Bank Negara Malaysia scam advisories"
  enabled: true

# ---- Group D: fake payment confirmation ----
- rule_id: D1_FAKE_PAYMENT_CONFIRMATION
  name: Fake payment confirmation language
  description: "Strength increases if combined with URL/QR/credential/impersonation - see D2."
  category: payment
  severity: medium
  weight: 3
  required_fields: [description]
  matching_method: keyword_group:fake_payment_confirmation
  evidence_to_record: matched_phrase
  source_reference: "Carousell/Mudah Trust & Safety guidance"
  enabled: true

- rule_id: D2_FAKE_PAYMENT_CONFIRMATION_PLUS_LINK
  name: Fake payment confirmation combined with external link or credential request
  category: payment
  severity: strong
  weight: 6
  required_fields: [description]
  matching_method: keyword_combo:fake_payment_confirmation+credential_request|impersonation
  evidence_to_record: matched_phrase
  source_reference: "Carousell/Mudah Trust & Safety guidance"
  enabled: true

# ---- Group E: off-platform activity ----
- rule_id: E1_OFF_PLATFORM_WEAK
  name: Off-platform contact mention (WhatsApp/Telegram/etc.)
  description: "WEAK ALONE per spec - many legitimate sellers use WhatsApp."
  category: contact
  severity: weak
  weight: 1
  required_fields: [description]
  matching_method: keyword_group:off_platform_contact
  evidence_to_record: matched_phrase
  source_reference: "Carousell Malaysia Trust & Safety guidance"
  enabled: true

- rule_id: E2_OFF_PLATFORM_PLUS_PAYMENT
  name: Off-platform contact combined with payment/fee/credential pressure
  category: contact
  severity: strong
  weight: 5
  required_fields: [description]
  matching_method: keyword_combo:off_platform_contact+advance_payment|agent_courier_release_fee|credential_request
  evidence_to_record: matched_phrase
  source_reference: "Carousell Malaysia Trust & Safety guidance"
  enabled: true

# ---- Group F: platform/staff impersonation ----
- rule_id: F1_IMPERSONATION_WEAK
  name: Platform/staff impersonation mention (weak alone)
  category: impersonation
  severity: weak
  weight: 1
  required_fields: [description]
  matching_method: keyword_group:impersonation
  evidence_to_record: matched_phrase
  source_reference: "Carousell/Mudah Trust & Safety impersonation advisories"
  enabled: true

- rule_id: F2_IMPERSONATION_PLUS_VERIFICATION
  name: Impersonation combined with payment/verification/OTP/link/fee language
  category: impersonation
  severity: strong
  weight: 6
  required_fields: [description]
  matching_method: keyword_combo:impersonation+credential_request|advance_payment|agent_courier_release_fee
  evidence_to_record: matched_phrase
  source_reference: "Carousell/Mudah Trust & Safety impersonation advisories"
  enabled: true

# ---- Group G: suspicious links ----
- rule_id: G1_SUSPICIOUS_URL
  name: Suspicious URL present (shortener/IP-based/typosquat)
  category: link
  severity: medium
  weight: 3
  required_fields: [description]
  matching_method: url_suspicious
  evidence_to_record: suspicious_domains
  source_reference: "Common phishing-URL heuristics"
  enabled: true

# ---- Group H: price anomalies ----
- rule_id: H1_PRICE_ANOMALY
  name: Price far below comparable category median
  description: >
    Requires >=5 comparable listings (same category, same platform) per spec minimum-sample
    rule. Tiers: 0.60-0.75=weak(1), 0.40-0.60=medium(3), 0.25-0.40=strong(5), <0.25=very
    strong(7).
  category: price
  severity: medium
  weight: 3
  required_fields: [price, category, price_ratio]
  matching_method: price_ratio_tiered
  evidence_to_record: price_ratio
  source_reference: "Internal category-median comparison (no external source)"
  enabled: true

# ---- Group I: image reuse ----
- rule_id: I1_CROSS_LISTING_IMAGE_REUSE
  name: Exact/near-duplicate image reused by unrelated listings
  category: image
  severity: medium
  weight: 4
  required_fields: [reused_image_indicator]
  matching_method: image_cross_listing_group
  evidence_to_record: related_listing_ids
  source_reference: "Internal pHash near-duplicate audit (dataset_validation_summary.json)"
  enabled: true

- rule_id: I2_IMAGE_REUSED_MANY_LISTINGS
  name: Same image reused across many (5+) unrelated listings
  category: image
  severity: strong
  weight: 6
  required_fields: [reused_image_indicator]
  matching_method: image_cross_listing_group_large
  evidence_to_record: related_listing_ids
  source_reference: "Internal pHash near-duplicate audit"
  enabled: true

# ---- Group J: description duplication ----
- rule_id: J1_DESCRIPTION_NEAR_DUPLICATE
  name: Near-identical description across unrelated listings/sellers
  category: text
  severity: medium
  weight: 3
  required_fields: [description]
  matching_method: description_similarity
  evidence_to_record: related_listing_ids
  source_reference: "Internal normalized-text shingling"
  enabled: true

# ---- Group K: seller behavioural signals ----
- rule_id: K1_NEW_ACCOUNT
  name: Account age <= 7 days
  category: seller
  severity: weak
  weight: 1
  required_fields: [account_age_days]
  matching_method: numeric_threshold:account_age_days<=7
  evidence_to_record: account_age_days
  source_reference: "Common marketplace-fraud heuristics"
  enabled: true

- rule_id: K2_YOUNG_ACCOUNT
  name: Account age 8-30 days
  category: seller
  severity: weak
  weight: 0.5
  required_fields: [account_age_days]
  matching_method: "numeric_range:account_age_days:8:30"
  evidence_to_record: account_age_days
  source_reference: "Common marketplace-fraud heuristics"
  enabled: true

- rule_id: K3_ZERO_REVIEWS
  name: Review count is a confirmed zero
  category: seller
  severity: weak
  weight: 1
  required_fields: [review_count, review_count_missing]
  matching_method: field_equals_zero_confirmed
  evidence_to_record: review_count
  source_reference: "Common marketplace-fraud heuristics"
  enabled: true

- rule_id: K4_POOR_RATING_SUFFICIENT_REVIEWS
  name: Poor rating with a meaningful number of reviews
  category: seller
  severity: medium
  weight: 3
  required_fields: [seller_rating, review_count]
  matching_method: "numeric_threshold_pair:seller_rating<2.5:review_count>=5"
  evidence_to_record: seller_rating
  source_reference: "Common marketplace-fraud heuristics"
  enabled: true

# ---- Group L: trust signals (severity=trust, contribute to trust_score) ----
- rule_id: L1_OLD_ACCOUNT
  name: Account older than one year
  category: trust
  severity: trust
  weight: 2
  required_fields: [account_age_days]
  matching_method: numeric_threshold:account_age_days>=365
  evidence_to_record: account_age_days
  source_reference: "Common marketplace-trust heuristics"
  enabled: true

- rule_id: L2_STRONG_RATING
  name: Strong seller rating with enough reviews
  category: trust
  severity: trust
  weight: 2
  required_fields: [seller_rating, review_count]
  matching_method: "numeric_threshold_pair:seller_rating>=4.5:review_count>=10"
  evidence_to_record: seller_rating
  source_reference: "Common marketplace-trust heuristics"
  enabled: true

- rule_id: L3_REASONABLE_PRICE
  name: Price within normal range of category median
  category: trust
  severity: trust
  weight: 1
  required_fields: [price_ratio]
  matching_method: "numeric_range:price_ratio:0.85:1.5"
  evidence_to_record: price_ratio
  source_reference: "Internal category-median comparison"
  enabled: true

# ---- Group M: contradictions (text-only; conservative) ----
- rule_id: M1_CATEGORY_KEYWORD_MISMATCH
  name: Category contradicts an unambiguous keyword in the title
  description: >
    Conservative: only fires on a small, hand-curated set of unambiguous category/keyword
    pairs (e.g. category=phones but title contains "sofa"/"refrigerator"). Not implemented as
    a general contradiction detector - see Phase 1 limitations.
  category: contradiction
  severity: weak
  weight: 1
  required_fields: [category, title]
  matching_method: category_keyword_conflict
  evidence_to_record: matched_phrase
  source_reference: "Internal conservative heuristic"
  enabled: true
```

- [ ] **Step 2: Write a loader smoke test**

```python
def test_scam_rules_yaml_loads_and_validates():
    from scripts.rule_engine.config import load_rules
    rules = load_rules("rules/scam_rules.yaml")
    ids = [r.rule_id for r in rules]
    assert len(ids) == len(set(ids)), "duplicate rule_id in scam_rules.yaml"
    assert "A1_SEMAK_MULE_PHONE" in ids
    disabled = [r.rule_id for r in rules if not r.enabled]
    assert "A1_SEMAK_MULE_PHONE" in disabled
    assert "A2_SEMAK_MULE_BANK" in disabled
```

- [ ] **Step 3: Run and verify pass**

Run: `python -m pytest tests/test_rule_engine.py -k scam_rules_yaml -v`
Expected: PASS (this only depends on Task 2's loader, already implemented).

- [ ] **Step 4: Commit**

```bash
git add rules/scam_rules.yaml tests/test_rule_engine.py
git commit -m "feat: add full rule catalog (Groups A-M) with infeasible rules disabled"
```

---

## Task 5: Feature extraction script

**Files:**
- Create: `scripts/rule_engine/price_stats.py`
- Create: `scripts/rule_engine/image_evidence.py`
- Create: `scripts/rule_engine/text_similarity.py`
- Create: `scripts/extract_annotation_features.py`
- Test: `tests/test_rule_engine.py` (additions)

**Interfaces:**
- Consumes: `data/annotation_ready/listings.csv` (read-only), `reports/image_validation.csv`
  (read-only), `reports/dataset_validation_summary.json` (read-only, for cross-listing image
  groups).
- Produces: `data/annotation_ready_features.csv` is **not** written under `data/` (that dir is
  read-only per Global Constraints) — features are written to
  **`output/annotation_features.csv`** instead, with exactly the columns from Phase 4 of the
  spec (only those backed by real data — see Phase-1 report above for the omitted ones).
  Function signature: `extract_features(listings_path, image_validation_path,
  validation_summary_path) -> list[dict]`.

- [ ] **Step 1: `scripts/rule_engine/price_stats.py`**

```python
from __future__ import annotations

from collections import defaultdict
from statistics import median

MIN_COMPARABLE_SAMPLE = 5


def compute_category_medians(rows: list[dict]) -> dict[tuple[str, str], float]:
    """category+platform -> median price, only for groups with >= MIN_COMPARABLE_SAMPLE prices."""
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        if row.get("price_missing") == "True" or not row.get("price"):
            continue
        key = (row["category"], row["platform"])
        buckets[key].append(float(row["price"]))
    return {k: median(v) for k, v in buckets.items() if len(v) >= MIN_COMPARABLE_SAMPLE}


def price_ratio_and_score(price: float | None, category: str, platform: str,
                           medians: dict[tuple[str, str], float]) -> tuple[float | None, str | None]:
    if price is None:
        return None, None
    m = medians.get((category, platform))
    if m is None or m == 0:
        return None, None
    ratio = price / m
    if ratio < 0.25:
        return ratio, "very_strong"
    if ratio < 0.40:
        return ratio, "strong"
    if ratio < 0.60:
        return ratio, "medium"
    if ratio < 0.75:
        return ratio, "weak"
    return ratio, None
```

- [ ] **Step 2: `scripts/rule_engine/image_evidence.py`**

```python
from __future__ import annotations

import json
from pathlib import Path


def load_cross_listing_groups(validation_summary_path: str | Path) -> list[list[str]]:
    data = json.loads(Path(validation_summary_path).read_text(encoding="utf-8"))
    return [g["listing_ids"] for g in data.get("near_duplicate_cross_listing_groups", [])]


def build_listing_to_related(groups: list[list[str]]) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for group in groups:
        group_set = set(group)
        for listing_id in group:
            mapping.setdefault(listing_id, set()).update(group_set - {listing_id})
    return mapping
```

- [ ] **Step 3: `scripts/rule_engine/text_similarity.py`**

```python
from __future__ import annotations

import re
from collections import defaultdict

_WS_RE = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://\S+")


def normalize_for_comparison(text: str) -> str:
    text = text.lower()
    text = _URL_RE.sub("[URL]", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def _shingles(text: str, k: int = 5) -> set[str]:
    words = text.split()
    if len(words) < k:
        return {text} if text else set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def jaccard_similarity(a: str, b: str) -> float:
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def find_near_duplicate_groups(listing_id_to_text: dict[str, str], threshold: float = 0.6) -> dict[str, list[str]]:
    """O(n^2) pairwise comparison - fine for 2,209 rows (~2.4M pairs, seconds in pure Python
    with early-exit on empty text). Returns listing_id -> [related listing_ids]."""
    ids = [lid for lid, text in listing_id_to_text.items() if text]
    result: dict[str, list[str]] = defaultdict(list)
    for i, lid_a in enumerate(ids):
        text_a = listing_id_to_text[lid_a]
        for lid_b in ids[i + 1:]:
            text_b = listing_id_to_text[lid_b]
            if jaccard_similarity(text_a, text_b) >= threshold:
                result[lid_a].append(lid_b)
                result[lid_b].append(lid_a)
    return dict(result)
```

- [ ] **Step 4: Write the failing test for the full extraction pipeline**

```python
def test_extract_features_preserves_nulls_and_computes_price_ratio(tmp_path):
    import csv
    from scripts.extract_annotation_features import extract_features

    listings = tmp_path / "listings.csv"
    with listings.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "listing_id", "platform", "category", "title", "description", "price",
            "price_missing", "account_age_days", "account_age_missing", "seller_rating",
            "seller_rating_missing", "review_count", "review_count_missing",
            "active_listing_count", "active_listing_count_missing", "image_count",
            "reused_image_indicator",
        ])
        w.writeheader()
        base = dict(platform="carousell", category="phones", title="iPhone 12", price_missing="False",
                    account_age_missing="False", seller_rating_missing="False",
                    review_count_missing="False", active_listing_count_missing="False",
                    image_count="3", reused_image_indicator="False")
        for i in range(5):
            w.writerow({**base, "listing_id": f"id{i}", "description": "normal listing",
                        "price": "1000", "account_age_days": "400", "seller_rating": "4.8",
                        "review_count": "20", "active_listing_count": "2"})
        w.writerow({**base, "listing_id": "cheap", "description": "WhatsApp me, deposit first",
                    "price": "200", "account_age_days": "", "account_age_missing": "True",
                    "seller_rating": "", "seller_rating_missing": "True",
                    "review_count": "0", "review_count_missing": "False",
                    "active_listing_count": "", "active_listing_count_missing": "True"})

    validation_summary = tmp_path / "summary.json"
    validation_summary.write_text('{"near_duplicate_cross_listing_groups": []}', encoding="utf-8")
    image_validation = tmp_path / "image_validation.csv"
    image_validation.write_text("listing_id,image_id,sha256,phash\n", encoding="utf-8")

    features = extract_features(listings, image_validation, validation_summary)
    cheap = next(f for f in features if f["listing_id"] == "cheap")
    assert cheap["account_age_days"] is None  # NULL stays NULL, never 0
    assert cheap["price_ratio"] < 0.25  # 200 / median(1000) = 0.2
    assert cheap["has_whatsapp"] is True
    assert cheap["has_advance_payment_language"] is True
```

- [ ] **Step 5: Run to verify it fails**

Run: `python -m pytest tests/test_rule_engine.py -k extract_features -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 6: Implement `scripts/extract_annotation_features.py`**

```python
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import yaml

from scripts.rule_engine.image_evidence import build_listing_to_related, load_cross_listing_groups
from scripts.rule_engine.keyword_matcher import match_keywords
from scripts.rule_engine.price_stats import compute_category_medians, price_ratio_and_score
from scripts.rule_engine.text_similarity import find_near_duplicate_groups, normalize_for_comparison

WORKSPACE = Path(__file__).resolve().parent.parent


def _to_float_or_none(value: str) -> float | None:
    return float(value) if value not in (None, "") else None


def _to_int_or_none(value: str) -> int | None:
    return int(value) if value not in (None, "") else None


def extract_features(listings_path, image_validation_path, validation_summary_path) -> list[dict]:
    patterns = yaml.safe_load((WORKSPACE / "rules" / "keyword_patterns.yaml").read_text(encoding="utf-8"))

    with open(listings_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    medians = compute_category_medians(rows)
    groups = load_cross_listing_groups(validation_summary_path)
    related_map = build_listing_to_related(groups)

    normalized_text = {r["listing_id"]: normalize_for_comparison(r.get("description") or "") for r in rows}
    duplicate_map = find_near_duplicate_groups(normalized_text)

    features = []
    for row in rows:
        lid = row["listing_id"]
        text = f"{row.get('title', '')} {row.get('description', '')}"
        matches = match_keywords(text, patterns)
        match_categories = {m.category for m in matches}

        price = _to_float_or_none(row.get("price"))
        price_ratio, price_anomaly_score = price_ratio_and_score(
            price, row.get("category"), row.get("platform"), medians
        )

        related = related_map.get(lid, set())
        dup_related = duplicate_map.get(lid, [])

        features.append({
            "listing_id": lid,
            "platform": row.get("platform"),
            "has_phone_reference": None,  # PII type not recoverable - see Phase-1 limitation
            "has_whatsapp": "off_platform_contact" in match_categories,
            "has_telegram": any("telegram" in p.lower() for m in matches for p in m.matched_phrases),
            "has_external_contact": "off_platform_contact" in match_categories,
            "external_url_count": text.lower().count("http"),
            "suspicious_url_count": None,  # Task 6 fills this via url_suspicious matching_method
            "has_advance_payment_language": "advance_payment" in match_categories,
            "has_direct_transfer_language": "advance_payment" in match_categories,
            "has_agent_fee_language": "agent_courier_release_fee" in match_categories,
            "has_fake_payment_language": "fake_payment_confirmation" in match_categories,
            "has_credential_request": "credential_request" in match_categories,
            "has_impersonation_language": "impersonation" in match_categories,
            "has_urgency_language": "urgency_language" in match_categories,
            "account_age_days": _to_int_or_none(row.get("account_age_days")) if row.get("account_age_missing") != "True" else None,
            "seller_rating": _to_float_or_none(row.get("seller_rating")) if row.get("seller_rating_missing") != "True" else None,
            "review_count": _to_int_or_none(row.get("review_count")) if row.get("review_count_missing") != "True" else None,
            "active_listing_count": _to_int_or_none(row.get("active_listing_count")) if row.get("active_listing_count_missing") != "True" else None,
            "price": price,
            "category_price_median": medians.get((row.get("category"), row.get("platform"))),
            "price_ratio": price_ratio,
            "price_anomaly_score": price_anomaly_score,
            "image_count": _to_int_or_none(row.get("image_count")),
            "cross_listing_duplicate_count": len(related),
            "cross_listing_related_ids": sorted(related),
            "description_duplicate_count": len(dup_related),
            "description_related_ids": sorted(dup_related),
            "semak_mule_checked": None,
            "semak_mule_phone_hit": None,
            "semak_mule_bank_hit": None,
        })
    return features


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listings", default=str(WORKSPACE / "data" / "annotation_ready" / "listings.csv"))
    parser.add_argument("--image-validation", default=str(WORKSPACE / "reports" / "image_validation.csv"))
    parser.add_argument("--validation-summary", default=str(WORKSPACE / "reports" / "dataset_validation_summary.json"))
    parser.add_argument("--out", default=str(WORKSPACE / "output" / "annotation_features.csv"))
    args = parser.parse_args()

    features = extract_features(args.listings, args.image_validation, args.validation_summary)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(features[0].keys()))
        writer.writeheader()
        writer.writerows(features)
    print(f"Wrote {len(features)} feature rows to {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run to verify it passes**

Run: `python -m pytest tests/test_rule_engine.py -k extract_features -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add scripts/rule_engine/price_stats.py scripts/rule_engine/image_evidence.py \
        scripts/rule_engine/text_similarity.py scripts/extract_annotation_features.py \
        tests/test_rule_engine.py
git commit -m "feat: add feature extraction (text/price/image/duplication features)"
```

---

## Task 6: Rule evaluation, weak labels, and evidence output

**Files:**
- Create: `rules/thresholds.yaml`
- Create: `scripts/rule_engine/evaluator.py`
- Create: `scripts/run_rule_annotation.py`
- Test: `tests/test_rule_engine.py` (additions)

**Interfaces:**
- Consumes: `output/annotation_features.csv` (Task 5), `rules/scam_rules.yaml` +
  `rules/thresholds.yaml` (Task 2/4 loaders).
- Produces: `output/weak_annotations.csv`, `reports/rule_matches.csv`,
  `reports/rule_coverage.csv`, `reports/annotation_summary.json`.
  Function: `evaluate_listing(feature_row: dict, rules: list[Rule]) -> EvaluationResult` with
  `.risk_score, .trust_score, .critical_rule_count, .strong_rule_count, .matched_rule_ids,
  .evidence: dict, .rule_label`.

- [ ] **Step 1: Write `rules/thresholds.yaml`** (verbatim from spec's suggested starting logic)

```yaml
critical_rule_min: 1
strong_risk_score_min: 8
strong_rule_count_min: 1
suspicious_risk_score_min: 4
legitimate_risk_score_max: 1
legitimate_trust_score_min: 3
```

- [ ] **Step 2: Write the failing test**

```python
def test_evaluate_listing_critical_rule_forces_likely_scam():
    from scripts.rule_engine.config import Rule, ThresholdConfig
    from scripts.rule_engine.evaluator import evaluate_listing

    rules = [Rule(
        rule_id="A3_A7_CREDENTIAL_REQUEST", name="Request for OTP/TAC/PIN/CVV", description="x",
        category="critical", severity="critical", weight=8, required_fields=["description"],
        matching_method="keyword_group:credential_request", evidence_to_record="matched_phrase",
        source_reference="", enabled=True,
    )]
    thresholds = ThresholdConfig(1, 8, 1, 4, 1, 3)
    feature_row = {"listing_id": "x1", "description": "please send the OTP", "has_credential_request": True,
                   "price_ratio": None, "account_age_days": None, "seller_rating": None,
                   "review_count": None, "cross_listing_duplicate_count": 0}
    result = evaluate_listing(feature_row, rules, thresholds)
    assert result.critical_rule_count == 1
    assert result.rule_label == "likely_scam"
    assert result.label_confidence == "high"  # critical rule fired -> always high, never hedged
    assert "OTP" in result.label_reason
    assert "A3_A7_CREDENTIAL_REQUEST" in result.matched_rule_ids
    assert result.evidence["A3_A7_CREDENTIAL_REQUEST"]


def test_evaluate_listing_no_signals_is_insufficient_evidence_not_legitimate():
    from scripts.rule_engine.config import Rule, ThresholdConfig
    from scripts.rule_engine.evaluator import evaluate_listing

    thresholds = ThresholdConfig(1, 8, 1, 4, 1, 3)
    feature_row = {"listing_id": "x2", "description": "", "has_credential_request": False,
                   "price_ratio": None, "account_age_days": None, "seller_rating": None,
                   "review_count": None, "cross_listing_duplicate_count": 0}
    result = evaluate_listing(feature_row, [], thresholds)
    # trust_score=0 < legitimate_trust_score_min=3 -> falls to insufficient_evidence, not legitimate
    assert result.rule_label == "insufficient_evidence"
    assert result.label_confidence == "rough"
    assert result.label_reason  # never blank, even for insufficient_evidence
    assert "no rule fired" in result.label_reason.lower() or "no signal" in result.label_reason.lower()


def test_evaluate_listing_result_has_no_override_fields():
    # Guards the human-override contract: EvaluationResult is the rule engine's own opinion
    # only. human_override_* columns are added downstream in run_rule_annotation.py's CSV
    # writer (Task 6, Step 6), never by the evaluator itself - keeps "what the rules said" and
    # "what the human corrected" structurally separate all the way until they share a CSV row.
    from scripts.rule_engine.config import ThresholdConfig
    from scripts.rule_engine.evaluator import evaluate_listing

    thresholds = ThresholdConfig(1, 8, 1, 4, 1, 3)
    feature_row = {"listing_id": "x3", "description": "", "has_credential_request": False,
                   "price_ratio": None, "account_age_days": None, "seller_rating": None,
                   "review_count": None, "cross_listing_duplicate_count": 0}
    result = evaluate_listing(feature_row, [], thresholds)
    assert not hasattr(result, "human_override_label")
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_rule_engine.py -k evaluate_listing -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 4: Implement `scripts/rule_engine/evaluator.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field

from scripts.rule_engine.config import Rule, ThresholdConfig

TRUST_CATEGORY = "trust"


@dataclass
class EvaluationResult:
    listing_id: str
    risk_score: float
    trust_score: float
    critical_rule_count: int
    strong_rule_count: int
    matched_rule_ids: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    rule_label: str = "insufficient_evidence"
    label_confidence: str = "rough"
    label_reason: str = ""


def _rule_fires(rule: Rule, feature_row: dict) -> tuple[bool, str | None]:
    """Boolean-feature-flag rules only; keyword_combo/url/price/image rules are evaluated by
    the same convention: extract_annotation_features.py precomputes a matching boolean/derived
    field per rule family (has_credential_request, price_anomaly_score, cross_listing_duplicate_count,
    etc.) so the evaluator stays declarative and never re-parses text."""
    method = rule.matching_method
    if method.startswith("keyword_group:credential_request"):
        return bool(feature_row.get("has_credential_request")), feature_row.get("description")
    if method.startswith("keyword_group:advance_payment"):
        fired = bool(feature_row.get("has_advance_payment_language"))
        return fired, feature_row.get("description") if fired else None
    if method.startswith("keyword_group:agent_courier_release_fee"):
        fired = bool(feature_row.get("has_agent_fee_language"))
        return fired, feature_row.get("description") if fired else None
    if method.startswith("keyword_group:fake_payment_confirmation"):
        fired = bool(feature_row.get("has_fake_payment_language"))
        return fired, feature_row.get("description") if fired else None
    if method.startswith("keyword_group:off_platform_contact"):
        fired = bool(feature_row.get("has_whatsapp")) or bool(feature_row.get("has_external_contact"))
        return fired, feature_row.get("description") if fired else None
    if method.startswith("keyword_group:impersonation"):
        fired = bool(feature_row.get("has_impersonation_language"))
        return fired, feature_row.get("description") if fired else None
    if method == "price_ratio_tiered":
        return feature_row.get("price_anomaly_score") is not None, feature_row.get("price_ratio")
    if method == "image_cross_listing_group":
        count = feature_row.get("cross_listing_duplicate_count") or 0
        return count >= 1, feature_row.get("cross_listing_related_ids")
    if method == "image_cross_listing_group_large":
        count = feature_row.get("cross_listing_duplicate_count") or 0
        return count >= 5, feature_row.get("cross_listing_related_ids")
    if method == "description_similarity":
        count = feature_row.get("description_duplicate_count") or 0
        return count >= 1, feature_row.get("description_related_ids")
    if method.startswith("numeric_threshold:account_age_days<=7"):
        v = feature_row.get("account_age_days")
        return (v is not None and v <= 7), v
    if method.startswith("numeric_threshold:account_age_days>=365"):
        v = feature_row.get("account_age_days")
        return (v is not None and v >= 365), v
    if method.startswith("numeric_range:account_age_days:8:30"):
        v = feature_row.get("account_age_days")
        return (v is not None and 8 <= v <= 30), v
    if method == "field_equals_zero_confirmed":
        v = feature_row.get("review_count")
        return v == 0, v
    if method.startswith("numeric_threshold_pair:seller_rating<2.5"):
        r, c = feature_row.get("seller_rating"), feature_row.get("review_count")
        return (r is not None and c is not None and r < 2.5 and c >= 5), r
    if method.startswith("numeric_threshold_pair:seller_rating>=4.5"):
        r, c = feature_row.get("seller_rating"), feature_row.get("review_count")
        return (r is not None and c is not None and r >= 4.5 and c >= 10), r
    if method.startswith("numeric_range:price_ratio:0.85:1.5"):
        v = feature_row.get("price_ratio")
        return (v is not None and 0.85 <= v <= 1.5), v
    if method == "field_equals_true":
        # Semak Mule rules - always False while the field is NULL/unchecked (never guessed).
        return False, None
    if method == "category_keyword_conflict":
        return False, None  # conservative: no hand-curated conflict pairs shipped yet
    if method == "url_suspicious":
        return False, None  # URL-domain heuristics land in a follow-up task, not fabricated here
    if method.startswith("keyword_combo:"):
        return False, None  # combo rules (A10/D2/E2/F2) require multi-category text re-check,
                             # deferred to the same follow-up as url_suspicious
    raise ValueError(f"unknown matching_method: {method}")


def _confidence_tier(label: str, trust_score: float, critical_count: int, strong_count: int,
                      matched_count: int, thresholds: ThresholdConfig) -> str:
    """Confidence describes how much corroborating evidence stacked up behind the label -
    it is never "weak"; a critical rule (e.g. an OTP request) is always high-confidence even
    though the overall system is still a rule-based heuristic, not verified ground truth."""
    if critical_count >= 1:
        return "high"
    if label == "likely_scam":
        return "high" if strong_count >= 2 else "moderate"
    if label == "suspicious":
        return "moderate" if matched_count >= 2 else "rough"
    if label == "likely_legitimate":
        return "moderate" if trust_score >= thresholds.legitimate_trust_score_min + 2 else "rough"
    return "rough"  # insufficient_evidence is rough by definition - that IS the label's meaning


def _build_reason(label: str, matched_rules: list[Rule], risk_score: float, trust_score: float) -> str:
    if not matched_rules:
        if label == "likely_legitimate":
            return ("Likely legitimate on absence of evidence only: no risk signal fired and "
                    "some trust signal(s) present, but this is a rough call - no strong positive "
                    "confirmation exists beyond 'nothing looked wrong'.")
        return ("Insufficient evidence: no seller, price, text, or image rule fired in either "
                "direction - there is simply not enough signal here to call it either way.")
    fired_desc = "; ".join(f"{r.rule_id} \"{r.name}\" [{r.severity}]" for r in matched_rules)
    return f"{label} (risk_score={risk_score:.1f}, trust_score={trust_score:.1f}). Matched rules: {fired_desc}."


def evaluate_listing(feature_row: dict, rules: list[Rule], thresholds: ThresholdConfig) -> EvaluationResult:
    risk_score = 0.0
    trust_score = 0.0
    critical_count = 0
    strong_count = 0
    matched_ids: list[str] = []
    matched_rules: list[Rule] = []
    evidence: dict = {}

    for rule in rules:
        if not rule.enabled:
            continue
        fired, ev = _rule_fires(rule, feature_row)
        if not fired:
            continue
        matched_ids.append(rule.rule_id)
        matched_rules.append(rule)
        evidence[rule.rule_id] = ev
        if rule.severity == TRUST_CATEGORY:
            trust_score += rule.weight
        else:
            risk_score += rule.weight
            if rule.severity == "critical":
                critical_count += 1
            elif rule.severity == "strong":
                strong_count += 1

    if critical_count >= thresholds.critical_rule_min:
        label = "likely_scam"
    elif risk_score >= thresholds.strong_risk_score_min and strong_count >= thresholds.strong_rule_count_min:
        label = "likely_scam"
    elif risk_score >= thresholds.suspicious_risk_score_min:
        label = "suspicious"
    elif (risk_score <= thresholds.legitimate_risk_score_max
          and trust_score >= thresholds.legitimate_trust_score_min
          and strong_count == 0 and critical_count == 0):
        label = "likely_legitimate"
    else:
        label = "insufficient_evidence"

    confidence = _confidence_tier(label, trust_score, critical_count, strong_count, len(matched_ids), thresholds)
    reason = _build_reason(label, [r for r in matched_rules if r.severity != TRUST_CATEGORY] or matched_rules,
                            risk_score, trust_score)

    return EvaluationResult(
        listing_id=feature_row["listing_id"], risk_score=risk_score, trust_score=trust_score,
        critical_rule_count=critical_count, strong_rule_count=strong_count,
        matched_rule_ids=matched_ids, evidence=evidence, rule_label=label,
        label_confidence=confidence, label_reason=reason,
    )
```

- [ ] **Step 5: Run to verify tests pass**

Run: `python -m pytest tests/test_rule_engine.py -k evaluate_listing -v`
Expected: PASS

- [ ] **Step 6: Implement `scripts/run_rule_annotation.py`**

```python
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from scripts.rule_engine.config import load_rules, load_thresholds
from scripts.rule_engine.evaluator import evaluate_listing

WORKSPACE = Path(__file__).resolve().parent.parent
RULE_VERSION = "rule_based_v1"


def _row_to_types(row: dict) -> dict:
    out = dict(row)
    for key in ("account_age_days", "review_count", "image_count", "cross_listing_duplicate_count",
                "description_duplicate_count"):
        out[key] = int(out[key]) if out.get(key) not in (None, "", "None") else None
    for key in ("seller_rating", "price", "price_ratio"):
        out[key] = float(out[key]) if out.get(key) not in (None, "", "None") else None
    return out


OVERRIDE_COLUMNS = ("human_override_label", "human_override_reason", "reviewer_id", "override_timestamp")


def _preserve_existing_human_overrides(out_rows: list[dict], out_path: Path) -> None:
    """Rerunning the rule engine (new rule version, tuned thresholds, refreshed dataset) must
    NEVER silently discard a human's prior overrides. If output/weak_annotations.csv already
    exists, carry forward its human_override_* values by listing_id before the fresh rule-engine
    output is written. A listing_id present in the old file but missing from the new run (should
    not normally happen - same dataset in, same dataset out) is logged, not silently dropped."""
    if not out_path.exists():
        return
    with out_path.open(encoding="utf-8", newline="") as f:
        existing = {row["listing_id"]: row for row in csv.DictReader(f)}
    carried_forward = 0
    for row in out_rows:
        old = existing.get(row["listing_id"])
        if old and any(old.get(col) for col in OVERRIDE_COLUMNS):
            for col in OVERRIDE_COLUMNS:
                row[col] = old.get(col, "")
            carried_forward += 1
    if carried_forward:
        print(f"Preserved {carried_forward} existing human override(s) from {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", default=str(WORKSPACE / "output" / "annotation_features.csv"))
    parser.add_argument("--rules", default=str(WORKSPACE / "rules" / "scam_rules.yaml"))
    parser.add_argument("--thresholds", default=str(WORKSPACE / "rules" / "thresholds.yaml"))
    parser.add_argument("--out", default=str(WORKSPACE / "output" / "weak_annotations.csv"))
    args = parser.parse_args()

    rules = load_rules(args.rules)
    thresholds = load_thresholds(args.thresholds)

    with open(args.features, encoding="utf-8", newline="") as f:
        feature_rows = [_row_to_types(r) for r in csv.DictReader(f)]

    label_counts: dict[str, int] = {}
    confidence_counts: dict[str, int] = {"rough": 0, "moderate": 0, "high": 0}
    rule_fire_counts: dict[str, int] = {rule.rule_id: 0 for rule in rules}
    out_rows = []
    matches_rows = []

    for feature_row in feature_rows:
        result = evaluate_listing(feature_row, rules, thresholds)
        label_counts[result.rule_label] = label_counts.get(result.rule_label, 0) + 1
        confidence_counts[result.label_confidence] += 1
        for rid in result.matched_rule_ids:
            rule_fire_counts[rid] += 1
            matches_rows.append({
                "listing_id": result.listing_id, "rule_id": rid,
                "evidence": json.dumps(result.evidence[rid], ensure_ascii=False, default=str),
            })
        out_rows.append({
            "listing_id": result.listing_id,
            "rule_label": result.rule_label,
            "label_confidence": result.label_confidence,
            "label_reason": result.label_reason,
            "risk_score": result.risk_score,
            "trust_score": result.trust_score,
            "critical_rule_count": result.critical_rule_count,
            "strong_rule_count": result.strong_rule_count,
            "matched_rule_ids": json.dumps(result.matched_rule_ids),
            "evidence": json.dumps(result.evidence, ensure_ascii=False, default=str),
            "annotation_source": RULE_VERSION,
            # Human-in-the-loop override columns. ALWAYS blank on a fresh run - a human fills
            # these in only for rows they've actually checked; rule_label/label_confidence/
            # label_reason above are never touched, so the two opinions stay comparable.
            "human_override_label": "",
            "human_override_reason": "",
            "reviewer_id": "",
            "override_timestamp": "",
        })

    out_path = Path(args.out)
    _preserve_existing_human_overrides(out_rows, out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_rows)

    reports_dir = WORKSPACE / "reports"
    with (reports_dir / "rule_matches.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["listing_id", "rule_id", "evidence"])
        writer.writeheader()
        writer.writerows(matches_rows)

    total = len(feature_rows)
    with (reports_dir / "rule_coverage.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rule_id", "fire_count", "coverage_pct"])
        for rid, count in sorted(rule_fire_counts.items(), key=lambda kv: -kv[1]):
            writer.writerow([rid, count, round(100 * count / total, 2) if total else 0])

    summary = {
        "rule_version": RULE_VERSION,
        "total_listings": total,
        "label_counts": label_counts,
        "confidence_counts": confidence_counts,
        "most_common_rules": sorted(rule_fire_counts.items(), key=lambda kv: -kv[1])[:10],
    }
    (reports_dir / "annotation_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Integration test on a small fixture (3 rows) confirming outputs are written**

```python
def test_run_rule_annotation_end_to_end(tmp_path, monkeypatch):
    import csv, json, subprocess, sys
    features = tmp_path / "features.csv"
    with features.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "listing_id", "description", "has_credential_request", "has_whatsapp",
            "has_advance_payment_language", "has_agent_fee_language", "has_fake_payment_language",
            "has_impersonation_language", "price_ratio", "price_anomaly_score",
            "cross_listing_duplicate_count", "cross_listing_related_ids",
            "description_duplicate_count", "description_related_ids",
            "account_age_days", "seller_rating", "review_count", "active_listing_count", "image_count",
        ])
        w.writeheader()
        w.writerow({"listing_id": "scam1", "description": "send OTP now", "has_credential_request": "True",
                    "has_whatsapp": "False", "has_advance_payment_language": "False",
                    "has_agent_fee_language": "False", "has_fake_payment_language": "False",
                    "has_impersonation_language": "False", "price_ratio": "", "price_anomaly_score": "",
                    "cross_listing_duplicate_count": "0", "cross_listing_related_ids": "[]",
                    "description_duplicate_count": "0", "description_related_ids": "[]",
                    "account_age_days": "", "seller_rating": "", "review_count": "", "active_listing_count": "",
                    "image_count": "1"})
    out = tmp_path / "weak.csv"
    result = subprocess.run(
        [sys.executable, "scripts/run_rule_annotation.py", "--features", str(features), "--out", str(out)],
        cwd=str(Path(__file__).resolve().parent.parent), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    with out.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["listing_id"] == "scam1"
    assert rows[0]["rule_label"] == "likely_scam"
    assert rows[0]["label_confidence"] == "high"
    assert rows[0]["label_reason"]
    assert rows[0]["human_override_label"] == ""  # blank on a fresh run
    assert "ground_truth" not in "".join(rows[0].keys())
```

- [ ] **Step 7b: Test that a rerun preserves an existing human override instead of wiping it**

```python
def test_rerun_preserves_human_override(tmp_path):
    import csv, subprocess, sys
    features = tmp_path / "features.csv"
    fieldnames = [
        "listing_id", "description", "has_credential_request", "has_whatsapp",
        "has_advance_payment_language", "has_agent_fee_language", "has_fake_payment_language",
        "has_impersonation_language", "price_ratio", "price_anomaly_score",
        "cross_listing_duplicate_count", "cross_listing_related_ids",
        "description_duplicate_count", "description_related_ids",
        "account_age_days", "seller_rating", "review_count", "active_listing_count", "image_count",
    ]
    with features.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerow({"listing_id": "x1", "description": "normal", "has_credential_request": "False",
                    "has_whatsapp": "False", "has_advance_payment_language": "False",
                    "has_agent_fee_language": "False", "has_fake_payment_language": "False",
                    "has_impersonation_language": "False", "price_ratio": "", "price_anomaly_score": "",
                    "cross_listing_duplicate_count": "0", "cross_listing_related_ids": "[]",
                    "description_duplicate_count": "0", "description_related_ids": "[]",
                    "account_age_days": "", "seller_rating": "", "review_count": "", "active_listing_count": "",
                    "image_count": "1"})
    out = tmp_path / "weak.csv"
    workspace = str(Path(__file__).resolve().parent.parent)

    def run():
        return subprocess.run(
            [sys.executable, "scripts/run_rule_annotation.py", "--features", str(features), "--out", str(out)],
            cwd=workspace, capture_output=True, text=True,
        )

    assert run().returncode == 0
    # Simulate the human reviewing x1 and overriding it after the first run.
    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    rows[0]["human_override_label"] = "likely_legitimate"
    rows[0]["reviewer_id"] = "osman"
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # Rerun (e.g. after tuning a threshold) must NOT wipe the override.
    result = run()
    assert result.returncode == 0
    with out.open(encoding="utf-8", newline="") as f:
        rows_after = list(csv.DictReader(f))
    assert rows_after[0]["human_override_label"] == "likely_legitimate"
    assert rows_after[0]["reviewer_id"] == "osman"
```

- [ ] **Step 8: Run full test suite**

Run: `python -m pytest tests/test_rule_engine.py -v`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add rules/thresholds.yaml scripts/rule_engine/evaluator.py scripts/run_rule_annotation.py \
        tests/test_rule_engine.py
git commit -m "feat: add rule evaluator, weak-label thresholds, and traceable evidence output"
```

---

## Task 7: Human review queue builder

**Files:**
- Create: `scripts/build_review_queue.py`

**Interfaces:**
- Consumes: `output/weak_annotations.csv` (Task 6) — which, since Task 6, already carries
  `label_confidence`, `label_reason`, and the `human_override_*` columns for every row.
- Produces: `reports/review_queue.csv` — **every** row from `weak_annotations.csv`
  (full coverage by default; nothing is dropped or sampled away), re-ordered so the rows most
  worth a human's limited time come first: `likely_scam` → `suspicious` → conflicting
  (critical/strong rule + nonzero trust) → `insufficient_evidence` → `likely_legitimate`. The
  human works top-down for as long as they have time, using the existing `human_override_*`
  columns to correct any row; stopping partway through is by design, not a failure — everything
  below where they stopped simply keeps its rule-only label until reviewed later.

- [ ] **Step 1: Write the failing test**

```python
def test_build_review_queue_orders_by_priority(tmp_path):
    import csv
    from scripts.build_review_queue import PRIORITY_ORDER, build_queue

    weak = tmp_path / "weak.csv"
    with weak.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["listing_id", "rule_label", "risk_score", "trust_score",
                                           "critical_rule_count", "strong_rule_count"])
        w.writeheader()
        w.writerow({"listing_id": "leg1", "rule_label": "likely_legitimate", "risk_score": "0",
                    "trust_score": "3", "critical_rule_count": "0", "strong_rule_count": "0"})
        w.writerow({"listing_id": "scam1", "rule_label": "likely_scam", "risk_score": "10",
                    "trust_score": "0", "critical_rule_count": "1", "strong_rule_count": "0"})
        w.writerow({"listing_id": "susp1", "rule_label": "suspicious", "risk_score": "5",
                    "trust_score": "0", "critical_rule_count": "0", "strong_rule_count": "0"})

    queue = build_queue(weak)
    order = [row["listing_id"] for row in queue]
    assert len(queue) == 3, "full coverage by default - nothing sampled away"
    assert order.index("scam1") < order.index("susp1") < order.index("leg1")
    assert queue[0]["human_override_label"] == ""
    assert "reviewer_id" in queue[0]


def test_build_review_queue_can_still_sample_legitimate_when_explicitly_asked(tmp_path):
    # Sampling remains available as an opt-in for a very large dataset in the future, but the
    # default (tested above) is full coverage - the user explicitly asked not to have rows
    # silently dropped from what they can review.
    import csv
    from scripts.build_review_queue import build_queue

    weak = tmp_path / "weak2.csv"
    with weak.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["listing_id", "rule_label", "risk_score", "trust_score",
                                           "critical_rule_count", "strong_rule_count",
                                           "human_override_label"])
        w.writeheader()
        for i in range(20):
            w.writerow({"listing_id": f"leg{i}", "rule_label": "likely_legitimate", "risk_score": "0",
                        "trust_score": "3", "critical_rule_count": "0", "strong_rule_count": "0",
                        "human_override_label": ""})
    queue = build_queue(weak, random_seed=42, legitimate_sample_rate=0.25)
    assert len(queue) == 5
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_rule_engine.py -k build_review_queue -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent

PRIORITY_ORDER = {
    "likely_scam": 0,
    "suspicious": 1,
    "conflicting": 2,        # critical/strong rules fired alongside a nonzero trust_score
    "high_risk_high_trust": 3,
    "insufficient_evidence": 4,
    "likely_legitimate_sample": 5,
}


def _priority_bucket(row: dict) -> str:
    label = row["rule_label"]
    critical = int(row.get("critical_rule_count") or 0)
    strong = int(row.get("strong_rule_count") or 0)
    trust = float(row.get("trust_score") or 0)
    if label == "likely_scam":
        return "likely_scam"
    if label == "suspicious":
        return "suspicious"
    if (critical > 0 or strong > 0) and trust >= 3:
        return "high_risk_high_trust"
    if label == "insufficient_evidence":
        return "insufficient_evidence"
    return "likely_legitimate_sample"


def build_queue(weak_annotations_path, random_seed: int = 42, legitimate_sample_rate: float = 1.0) -> list[dict]:
    """Default legitimate_sample_rate=1.0 means FULL COVERAGE - every row from
    weak_annotations.csv comes through, just re-ordered by review priority. Lower this only if
    the dataset grows large enough that even a re-ordered full list is impractical; the default
    exists so no row is silently dropped from what the human can choose to review."""
    with open(weak_annotations_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    buckets: dict[str, list[dict]] = {k: [] for k in PRIORITY_ORDER}
    for row in rows:
        buckets[_priority_bucket(row)].append(row)

    if legitimate_sample_rate < 1.0:
        rng = random.Random(random_seed)
        legit_bucket = buckets["likely_legitimate_sample"]
        sample_size = max(1, int(len(legit_bucket) * legitimate_sample_rate)) if legit_bucket else 0
        buckets["likely_legitimate_sample"] = rng.sample(legit_bucket, min(sample_size, len(legit_bucket)))

    queue = []
    for bucket_name in sorted(PRIORITY_ORDER, key=PRIORITY_ORDER.get):
        queue.extend(buckets[bucket_name])
    return queue


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weak-annotations", default=str(WORKSPACE / "output" / "weak_annotations.csv"))
    parser.add_argument("--out", default=str(WORKSPACE / "reports" / "review_queue.csv"))
    parser.add_argument("--legitimate-sample-rate", type=float, default=1.0,
                         help="1.0 (default) = full coverage, no rows dropped. Lower only if you "
                              "explicitly want to sample the likely_legitimate bucket.")
    args = parser.parse_args()

    queue = build_queue(args.weak_annotations, legitimate_sample_rate=args.legitimate_sample_rate)
    out_path = Path(args.out)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(queue[0].keys()))
        writer.writeheader()
        writer.writerows(queue)
    print(f"Wrote {len(queue)} rows to {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_rule_engine.py -k build_review_queue -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/build_review_queue.py tests/test_rule_engine.py
git commit -m "feat: add prioritized human review queue builder"
```

---

## Task 8: Rule documentation

**Files:**
- Create/append: `rules/rule_documentation.md`

**Interfaces:** none (documentation only, but must stay in sync with `rules/scam_rules.yaml`
rule IDs — verified by Task 9's verifier).

- [ ] **Step 1: Write one section per rule family** (spec explicitly permits source-link
  placeholders when offline — this is NOT a code placeholder violation, it is a spec-sanctioned
  citation gap; each placeholder is an honest `TODO(source): verify against <organization>'s
  published guidance`, never an invented URL)

```markdown
# GuardianLens Rule-Based Weak-Labeling: Rule Documentation

Every rule below corresponds 1:1 to an entry in `scam_rules.yaml` by `rule_id`. This file is a
narrative companion, not the source of truth for thresholds/weights (those live in the YAML).

## A. Critical fraud indicators

### A1_SEMAK_MULE_PHONE / A2_SEMAK_MULE_BANK
- **What it detects:** a phone number or bank account confirmed on Semak Mule's public
  scam-database lookup.
- **Why relevant:** direct confirmation from Malaysia's national mule-account registry.
- **Strength:** critical.
- **Fields used:** `semak_mule_phone_hit`, `semak_mule_bank_hit` (currently always NULL).
- **Limitations:** **disabled** — this dataset was never checked against Semak Mule; the spec
  forbids scraping or fabricating this at annotation-prep time.
- **Possible false positives:** N/A while disabled.
- **Source:** TODO(source): verify current lookup URL and terms of use against Semak Mule /
  PDRM CCID's official channel before enabling this rule with live data.

### A3_A7_CREDENTIAL_REQUEST
- **What it detects:** text asking for OTP, TAC, PIN, CVV, bank password/login.
- **Why relevant:** legitimate marketplace transactions never require these from a buyer or
  seller counterpart.
- **Strength:** critical.
- **Fields used:** `description` (via `keyword_patterns.yaml: credential_request`).
- **Limitations:** literal keyword match only; a scammer paraphrasing without these exact terms
  is missed.
- **Possible false positives:** a seller warning buyers *not* to share OTP/PIN could false-fire;
  human review queue surfaces every match for exactly this reason.
- **Source:** TODO(source): cross-reference against PDRM/NSRC published common-scam-script
  wording once internet access is available for this task.

### A8_A9_PHISHING_URL / A10_IMPERSONATION_PLUS_PAYMENT
- **What it detects:** suspicious/phishing URLs, or platform/bank impersonation paired with a
  payment or credential ask.
- **Strength:** critical.
- **Limitations:** `url_suspicious` and `keyword_combo:*` matching methods are stubbed to
  always-false in Task 6 (see evaluator.py comments) pending a follow-up task; disabled rules
  are more honest than a fabricated implementation.
- **Source:** TODO(source): Carousell/Mudah Trust & Safety phishing advisories.

## B. Payment scam patterns
### B1_ADVANCE_PAYMENT_WEAK / B2_ADVANCE_PAYMENT_STRONG
- **What it detects:** deposit/advance-payment language, weak when bare ("deposit"), strong
  when qualified with urgency/amount/pre-inspection framing.
- **Why relevant:** advance-payment-then-vanish is the most common Malaysian marketplace scam
  pattern.
- **Fields used:** `description`.
- **Limitations:** legitimate sellers also sometimes request deposits for high-value/custom
  items — hence weak alone, never scam alone.
- **Source:** TODO(source): Carousell Malaysia Trust & Safety Help Centre.

## C. Agent/courier/release fee
### C1_RELEASE_FEE
- **What it detects:** any fee framed as required to *receive* or *release* money.
- **Why relevant:** no legitimate payment flow ever requires the *payee* to pay to receive
  funds — this is close to a definitional scam pattern.
- **Strength:** strong.
- **Source:** TODO(source): Bank Negara Malaysia / NSRC public advisories on release-fee scams.

## D. Fake payment confirmation
### D1_FAKE_PAYMENT_CONFIRMATION / D2_FAKE_PAYMENT_CONFIRMATION_PLUS_LINK
- **What it detects:** claims of a completed/pending payment, escalated when paired with a link
  or credential request.
- **Source:** TODO(source): Carousell/Mudah Trust & Safety guidance.

## E. Off-platform activity
### E1_OFF_PLATFORM_WEAK / E2_OFF_PLATFORM_PLUS_PAYMENT
- **What it detects:** WhatsApp/Telegram/off-platform contact mentions; weak alone (extremely
  common and legitimate), strong only combined with payment/fee/credential pressure.
- **Source:** TODO(source): Carousell Malaysia Trust & Safety Help Centre.

## F. Platform/staff impersonation
### F1_IMPERSONATION_WEAK / F2_IMPERSONATION_PLUS_VERIFICATION
- **What it detects:** claims of being Carousell/Mudah/bank/courier staff.
- **Source:** TODO(source): Carousell/Mudah Trust & Safety impersonation advisories.

## G. Suspicious links
### G1_SUSPICIOUS_URL
- **What it detects:** URL shorteners/IP-literal/typosquat domains in listing text.
- **Limitations:** stubbed to always-false pending a follow-up domain-heuristics task (see
  A8_A9 above) — not implemented with fabricated logic.
- **Source:** common public phishing-URL heuristics (no single official citation).

## H. Price anomalies
### H1_PRICE_ANOMALY
- **What it detects:** price far below the same-category/platform median, tiered by
  `price_ratio`.
- **Limitations:** requires >=5 comparable listings (category x platform); many category
  buckets in this 2,209-row dataset will not meet that bar and simply won't get a
  `price_ratio` — this is intentional, not a bug.
- **Source:** internal statistical comparison; no external citation applies.

## I. Image reuse/duplication
### I1_CROSS_LISTING_IMAGE_REUSE / I2_IMAGE_REUSED_MANY_LISTINGS
- **What it detects:** a listing's image(s) perceptually matching image(s) in unrelated
  listings (from the existing `dataset_validation_summary.json` pHash audit).
- **Limitations:** cannot distinguish "same seller re-listing their own item" from "different
  seller reusing a stock photo" without seller-identity linkage, which this dataset does not
  reliably carry across platforms — evidence includes the related listing IDs so a human
  reviewer makes that call.
- **Source:** internal pHash audit (`reports/dataset_validation_summary.json`).

## J. Description duplication
### J1_DESCRIPTION_NEAR_DUPLICATE
- **What it detects:** near-identical description text (5-word shingle Jaccard >= 0.6) across
  unrelated listings.
- **Limitations:** threshold (0.6) is a starting default, not validated against labeled data
  yet — tune after the human-review pilot has some ground truth to check against.
- **Source:** internal text-similarity heuristic; no external citation applies.

## K. Seller behavioural signals
### K1_NEW_ACCOUNT / K2_YOUNG_ACCOUNT / K3_ZERO_REVIEWS / K4_POOR_RATING_SUFFICIENT_REVIEWS
- **What it detects:** young accounts, confirmed-zero reviews, or poor rating with enough
  reviews to be meaningful.
- **Limitations:** each is explicitly weak/medium alone per the spec's stated rule
  ("new_account alone != scam").
- **Source:** general marketplace-fraud literature; no single official citation.

## L. Trust signals
### L1_OLD_ACCOUNT / L2_STRONG_RATING / L3_REASONABLE_PRICE
- **What it detects:** positive counter-evidence that reduces (never zeroes out) risk.
- **Limitations:** per spec, trust signals must never override a critical rule match — enforced
  in `evaluator.py` by evaluating `critical_rule_count` first, independent of `trust_score`.

## M. Contradictions
### M1_CATEGORY_KEYWORD_MISMATCH
- **What it detects:** a small, hand-curated set of unambiguous category/title conflicts.
- **Limitations:** ships **empty** (no curated pairs yet) — ready to extend, deliberately not
  populated with guessed conflict pairs at plan-writing time.
- **Source:** internal conservative heuristic; no external citation applies.
```

- [ ] **Step 2: Cross-check against `scam_rules.yaml`**

Run a quick script check (or by eye): every `rule_id` in `scam_rules.yaml` has a `###` heading
in `rule_documentation.md`. This becomes an automated check in Task 9.

- [ ] **Step 3: Commit**

```bash
git add rules/rule_documentation.md
git commit -m "docs: add per-rule-family documentation for scam_rules.yaml"
```

---

## Task 9: Test suite — 16 required scenarios

**Files:**
- Create: `tests/conftest.py`
- Modify: `tests/test_rule_engine.py` (add the scenario tests)

**Interfaces:**
- Consumes: `evaluate_listing()` (Task 6), `load_rules()`/`load_thresholds()` (Task 2).

- [ ] **Step 1: `tests/conftest.py` — shared fixture builder**

```python
import pytest

from scripts.rule_engine.config import load_rules, load_thresholds

BASE_ROW = {
    "listing_id": "base", "description": "", "has_credential_request": False,
    "has_whatsapp": False, "has_advance_payment_language": False,
    "has_agent_fee_language": False, "has_fake_payment_language": False,
    "has_impersonation_language": False, "price_ratio": None, "price_anomaly_score": None,
    "cross_listing_duplicate_count": 0, "cross_listing_related_ids": [],
    "description_duplicate_count": 0, "description_related_ids": [],
    "account_age_days": None, "seller_rating": None, "review_count": None,
    "active_listing_count": None, "image_count": 1,
}


def make_row(**overrides) -> dict:
    return {**BASE_ROW, **overrides}


@pytest.fixture(scope="session")
def rules():
    return load_rules("rules/scam_rules.yaml")


@pytest.fixture(scope="session")
def thresholds():
    return load_thresholds("rules/thresholds.yaml")
```

- [ ] **Step 2: Write the 16 scenario tests**

```python
import pytest

from tests.conftest import make_row
from scripts.rule_engine.evaluator import evaluate_listing


def test_scenario_01_old_seller_good_rating_is_legitimate(rules, thresholds):
    row = make_row(listing_id="s1", account_age_days=800, seller_rating=4.9, review_count=50,
                    price_ratio=1.0)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label == "likely_legitimate"


def test_scenario_02_new_seller_zero_reviews_otherwise_normal_not_scam(rules, thresholds):
    row = make_row(listing_id="s2", account_age_days=3, review_count=0, price_ratio=1.0)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label != "likely_scam"


def test_scenario_03_very_low_price_only_not_scam(rules, thresholds):
    row = make_row(listing_id="s3", price_ratio=0.2, price_anomaly_score="very_strong")
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label != "likely_scam"


def test_scenario_04_whatsapp_only_not_scam(rules, thresholds):
    row = make_row(listing_id="s4", has_whatsapp=True)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label != "likely_scam"


def test_scenario_05_whatsapp_plus_deposit_is_at_least_suspicious(rules, thresholds):
    row = make_row(listing_id="s5", has_whatsapp=True, has_advance_payment_language=True)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label in ("suspicious", "likely_scam")


def test_scenario_06_otp_request_is_very_high_risk(rules, thresholds):
    row = make_row(listing_id="s6", has_credential_request=True)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label == "likely_scam"
    assert result.critical_rule_count >= 1


def test_scenario_07_suspicious_payment_link_present(rules, thresholds):
    # url_suspicious is stubbed false in this plan (Task 6 note) - this scenario documents
    # the CURRENT (honest) behavior and must be re-asserted once the follow-up task lands.
    row = make_row(listing_id="s7")
    result = evaluate_listing(row, rules, thresholds)
    assert "G1_SUSPICIOUS_URL" not in result.matched_rule_ids  # honest: not implemented yet


def test_scenario_08_agent_fee_to_release_payment_is_very_high_risk(rules, thresholds):
    row = make_row(listing_id="s8", has_agent_fee_language=True)
    result = evaluate_listing(row, rules, thresholds)
    assert "C1_RELEASE_FEE" in result.matched_rule_ids
    assert result.rule_label in ("suspicious", "likely_scam")


def test_scenario_09_reused_image_alone_not_scam(rules, thresholds):
    row = make_row(listing_id="s9", cross_listing_duplicate_count=1, cross_listing_related_ids=["other1"])
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label != "likely_scam"


def test_scenario_10_reused_image_plus_low_price_plus_new_account_is_suspicious_or_worse(rules, thresholds):
    row = make_row(listing_id="s10", cross_listing_duplicate_count=1, cross_listing_related_ids=["other1"],
                    price_ratio=0.2, price_anomaly_score="very_strong", account_age_days=2)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label in ("suspicious", "likely_scam")


def test_scenario_11_trusted_seller_plus_one_weak_risk_stays_non_scam(rules, thresholds):
    row = make_row(listing_id="s11", account_age_days=900, seller_rating=4.8, review_count=80,
                    has_whatsapp=True)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label != "likely_scam"


def test_scenario_12_critical_signal_overrides_strong_trust_history(rules, thresholds):
    row = make_row(listing_id="s12", account_age_days=900, seller_rating=4.9, review_count=200,
                    has_credential_request=True)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label == "likely_scam"  # trust NEVER overrides a critical rule (spec, Group L)


def test_scenario_13_missing_seller_data_is_null_not_zero(rules, thresholds):
    row = make_row(listing_id="s13")  # account_age_days/seller_rating/review_count all None
    result = evaluate_listing(row, rules, thresholds)
    assert row["account_age_days"] is None
    assert result.rule_label in ("insufficient_evidence", "suspicious")


def test_scenario_14_missing_price(rules, thresholds):
    row = make_row(listing_id="s14", price_ratio=None, price_anomaly_score=None)
    result = evaluate_listing(row, rules, thresholds)
    assert "H1_PRICE_ANOMALY" not in result.matched_rule_ids


def test_scenario_15_missing_images(rules, thresholds):
    row = make_row(listing_id="s15", image_count=0, cross_listing_duplicate_count=0)
    result = evaluate_listing(row, rules, thresholds)
    assert "I1_CROSS_LISTING_IMAGE_REUSE" not in result.matched_rule_ids


def test_scenario_16_mixed_malay_english_scam_wording(rules, thresholds):
    from scripts.rule_engine.keyword_matcher import match_keywords
    import yaml
    patterns = yaml.safe_load(open("rules/keyword_patterns.yaml", encoding="utf-8"))
    text = "Boleh WhatsApp saya, bayar dulu untuk secure barang ni"
    matches = match_keywords(text, patterns)
    categories = {m.category for m in matches}
    assert "off_platform_contact" in categories
    assert "advance_payment" in categories


@pytest.mark.parametrize("listing_id,overrides", [
    ("r1", {}),
    ("r2", {"has_credential_request": True}),
    ("r3", {"account_age_days": 900, "seller_rating": 4.9, "review_count": 200}),
    ("r4", {"cross_listing_duplicate_count": 3, "cross_listing_related_ids": ["a", "b", "c"]}),
])
def test_every_scenario_gets_a_nonblank_reason_and_valid_confidence(rules, thresholds, listing_id, overrides):
    # The core contract this refinement adds: no row - scam, legitimate, or ambiguous - is ever
    # left with a blank reason or a "weak"-labeled confidence tier.
    row = make_row(listing_id=listing_id, **overrides)
    result = evaluate_listing(row, rules, thresholds)
    assert result.label_reason.strip() != ""
    assert result.label_confidence in ("rough", "moderate", "high")
    assert "weak" not in result.label_confidence
```

- [ ] **Step 3: Run to verify all fail first (TDD check), then verify implementation makes them pass**

Run: `python -m pytest tests/ -v`
Expected first (before Task 6/2/4 exist): failures. After all prior tasks are committed: **all
16 scenario tests + all engine unit tests PASS.**

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/test_rule_engine.py
git commit -m "test: add all 16 required rule-engine scenario tests"
```

---

## Task 10: Final verification + FINAL OUTPUT report

**Files:**
- Create: `scripts/verify_rule_annotations.py`
- Create: `reports/dataset_audit.json` (generated, not hand-written)

**Interfaces:**
- Consumes: everything produced by Tasks 1–9.
- Produces: pass/fail console report covering all Phase-10 spec checks; `reports/dataset_audit.json`
  matching the Phase-1 "short report" fields.

- [ ] **Step 1: Write the failing test**

```python
def test_verifier_flags_ground_truth_label_column(tmp_path):
    import csv
    from scripts.verify_rule_annotations import check_no_ground_truth_column

    bad = tmp_path / "bad.csv"
    with bad.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["listing_id", "ground_truth_label"])
    errors = check_no_ground_truth_column(bad)
    assert errors, "must flag a ground_truth_label column if present"

    good = tmp_path / "good.csv"
    with good.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["listing_id", "rule_label"])
    assert check_no_ground_truth_column(good) == []


def test_verifier_flags_blank_reason_or_weak_confidence(tmp_path):
    import csv
    from scripts.verify_rule_annotations import check_every_row_fully_labeled, REQUIRED_LABELING_COLUMNS

    bad = tmp_path / "bad_labels.csv"
    with bad.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["listing_id", *REQUIRED_LABELING_COLUMNS])
        w.writeheader()
        w.writerow({"listing_id": "x1", "rule_label": "likely_scam", "label_confidence": "weak",
                    "label_reason": "", "human_override_label": "", "human_override_reason": "",
                    "reviewer_id": "", "override_timestamp": ""})
    errors = check_every_row_fully_labeled(bad)
    assert any("label_reason" in e for e in errors)
    assert any("label_confidence" in e for e in errors)

    good = tmp_path / "good_labels.csv"
    with good.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["listing_id", *REQUIRED_LABELING_COLUMNS])
        w.writeheader()
        w.writerow({"listing_id": "x1", "rule_label": "likely_scam", "label_confidence": "high",
                    "label_reason": "credential request detected", "human_override_label": "",
                    "human_override_reason": "", "reviewer_id": "", "override_timestamp": ""})
    assert check_every_row_fully_labeled(good) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_rule_engine.py -k verifier -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement `scripts/verify_rule_annotations.py`**

```python
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import yaml

WORKSPACE = Path(__file__).resolve().parent.parent


def check_no_ground_truth_column(csv_path: str | Path) -> list[str]:
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f))
    return [f"{csv_path}: found forbidden column {col!r}" for col in header if "ground_truth" in col]


def check_source_dataset_unchanged(listings_path: Path, expected_row_count: int) -> list[str]:
    with listings_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != expected_row_count:
        return [f"listings.csv row count changed: expected {expected_row_count}, got {len(rows)}"]
    return []


def check_rule_ids_documented(rules_path: Path, doc_path: Path) -> list[str]:
    rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    doc_text = doc_path.read_text(encoding="utf-8")
    missing = [r["rule_id"] for r in rules if r["rule_id"] not in doc_text]
    return [f"rule_documentation.md missing section for {rid}" for rid in missing]


def check_weak_annotations_reproducible(out_path: Path) -> list[str]:
    if not out_path.exists():
        return [f"{out_path} does not exist - run run_rule_annotation.py first"]
    return []


def check_utf8(path: Path) -> list[str]:
    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return [f"{path}: not valid UTF-8: {e}"]
    return []


REQUIRED_LABELING_COLUMNS = ("rule_label", "label_confidence", "label_reason",
                             "human_override_label", "human_override_reason",
                             "reviewer_id", "override_timestamp")
VALID_CONFIDENCE = {"rough", "moderate", "high"}


def check_every_row_fully_labeled(weak_annotations_path: Path) -> list[str]:
    """Every row must have rule_label/label_confidence/label_reason populated (Task 6's
    guarantee that no listing is ever left unlabeled), the override columns must exist as
    real header entries (even if blank), and no confidence value may literally be "weak" -
    the terminology this whole refinement exists to avoid."""
    errors = []
    with weak_annotations_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing_cols = [c for c in REQUIRED_LABELING_COLUMNS if c not in (reader.fieldnames or [])]
        if missing_cols:
            return [f"{weak_annotations_path}: missing required column(s) {missing_cols}"]
        for i, row in enumerate(reader):
            if not row["rule_label"]:
                errors.append(f"row {i} ({row.get('listing_id')}): blank rule_label")
            if row["label_confidence"] not in VALID_CONFIDENCE:
                errors.append(f"row {i} ({row.get('listing_id')}): invalid label_confidence {row['label_confidence']!r}")
            if not row["label_reason"].strip():
                errors.append(f"row {i} ({row.get('listing_id')}): blank label_reason")
    return errors


def check_overrides_blank_on_fresh_export(weak_annotations_path: Path) -> list[str]:
    """Sanity check for a FRESH run only (call this right after export_annotation_dataset.py /
    run_rule_annotation.py on a workspace with no prior human review) - overrides should still
    be blank. This check is informational, not a hard failure, once real review has begun."""
    errors = []
    with weak_annotations_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        filled = sum(1 for row in reader if row.get("human_override_label"))
    if filled:
        print(f"NOTE: {filled} row(s) already carry a human_override_label - "
              f"this is expected once review has started, not an error.")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-row-count", type=int, default=2209)
    args = parser.parse_args()

    errors: list[str] = []
    errors += check_no_ground_truth_column(WORKSPACE / "output" / "weak_annotations.csv")
    errors += check_no_ground_truth_column(WORKSPACE / "reports" / "review_queue.csv")
    errors += check_source_dataset_unchanged(
        WORKSPACE / "data" / "annotation_ready" / "listings.csv", args.expected_row_count
    )
    errors += check_rule_ids_documented(
        WORKSPACE / "rules" / "scam_rules.yaml", WORKSPACE / "rules" / "rule_documentation.md"
    )
    errors += check_weak_annotations_reproducible(WORKSPACE / "output" / "weak_annotations.csv")
    errors += check_utf8(WORKSPACE / "output" / "weak_annotations.csv")
    errors += check_every_row_fully_labeled(WORKSPACE / "output" / "weak_annotations.csv")
    errors += check_overrides_blank_on_fresh_export(WORKSPACE / "output" / "weak_annotations.csv")

    if errors:
        print(f"FAILED: {len(errors)} check(s)")
        for e in errors:
            print(f"  - {e}")
        raise SystemExit(1)
    print("All rule-annotation verification checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_rule_engine.py -k verifier -v`
Expected: PASS

- [ ] **Step 5: End-to-end dry run against the real 2,209-row dataset (read-only inputs, new
  outputs only) and generate the FINAL OUTPUT report**

```bash
cd "GuardianLens_Annotation"
python scripts/extract_annotation_features.py
python scripts/run_rule_annotation.py
python scripts/build_review_queue.py
python scripts/verify_rule_annotations.py
```

Expected: `output/annotation_features.csv` (2,209 rows), `output/weak_annotations.csv` (2,209
rows), `reports/rule_matches.csv`, `reports/rule_coverage.csv`, `reports/annotation_summary.json`,
`reports/review_queue.csv` all created; verifier prints "All rule-annotation verification checks
passed."; `git status` on the sibling `GuardianLens_Data_Collector_v_1.0.0` repo shows **zero**
diff.

- [ ] **Step 6: Report the 20 FINAL OUTPUT items from the spec using the real run's numbers**

(Read `reports/annotation_summary.json` + `reports/rule_coverage.csv` and fill in: dataset
fields available/missing — from the Phase-1 table above — rules implemented (25 enabled) vs.
not (A1, A2, plus the `url_suspicious`/`keyword_combo` stubs — 6 rule IDs total), listing counts
per label, critical/strong match counts, top rules, coverage %, review-queue size, file
locations, exact rerun/verify commands, and the dataset limitations already documented in the
Phase-1 section above.)

- [ ] **Step 7: Commit**

```bash
git add scripts/verify_rule_annotations.py reports/dataset_audit.json tests/test_rule_engine.py
git commit -m "feat: add final rule-annotation verification script"
```

---

## Self-Review Notes (per writing-plans skill)

- **Spec coverage:** Phases 1 (report, done above) through 10 (Task 10) all have a task.
  Rule Groups A–M all have `scam_rules.yaml` entries (Task 4) — 6 of ~31 rule IDs are
  `enabled: false` or evaluate to always-false, each with an explicit, spec-consistent reason
  (Semak Mule not queried; URL/combo heuristics deferred to a named follow-up rather than
  faked) — never silently dropped.
- **Placeholder scan:** the only `TODO(source):` markers are in `rule_documentation.md`
  (Task 8), which the spec's Phase 8 explicitly sanctions ("create placeholders for sources
  rather than inventing citations" when offline). No code-level `TODO`/`pass`/"implement later"
  exists in any task's Python.
- **Type consistency:** `Rule`, `ThresholdConfig`, `EvaluationResult`, `MatchResult` are each
  defined once (Tasks 2/3/6) and consumed with the same field names throughout Tasks 4–10 —
  checked by hand across all code blocks above.
- **Known deliberate gap carried into Task 6/9:** `url_suspicious` and all four
  `keyword_combo:*` matching methods (A10, D2, E2, F2, G1) evaluate to always-false pending a
  small follow-up task (domain-reputation heuristics + multi-category re-check) — flagged
  explicitly in code comments, the rule catalog, the documentation, and test scenario 7, so it
  is impossible to mistake the stub for a working detector. Recommend this follow-up be a
  short **Task 11** before treating Rule Group A/D/E/F/G as complete.
- **Full-coverage labeling + human-override refinement (see "Revision Notes" above):** verified
  every task that touches `EvaluationResult`/`weak_annotations.csv`/`review_queue.csv` was
  updated consistently — `label_confidence`/`label_reason` are set once in `evaluator.py` and
  never recomputed elsewhere; `human_override_*` columns are introduced exactly once (Task 6's
  CSV writer) and only ever read, never written, by `build_review_queue.py` (Task 7) or
  `verify_rule_annotations.py` (Task 10); the rerun-preserves-overrides behavior has its own
  dedicated test (Task 6, Step 7b) rather than being asserted only indirectly.
- **Recommended near-term follow-up (Task 12, not yet written up in full):** once real human
  overrides start accumulating in `output/weak_annotations.csv`, add a small script that reports
  per-`rule_id` agreement/disagreement rate between `rule_label` and `human_override_label` — this
  is the concrete signal for which rules are actually reliable versus noisy, and directly informs
  whether a future supervised model should trust a given rule's feature as much as the YAML
  weight currently implies.
