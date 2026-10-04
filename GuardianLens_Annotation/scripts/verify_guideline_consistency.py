"""Automated consistency check across the annotation guideline layer.

Does NOT touch the rule engine, data, or the pilot -- this only reads
annotation/guidelines/*, the top-level ANNOTATION_GUIDE.md pointer, annotation/label_definitions.md,
annotation/examples/worked_examples.md, and the two schema JSON files' confidence-field notes.

Checks that the formal signal taxonomy (weak/strong/critical), the scam/fraud boundary rule, the
evidence sufficiency gate, the conflict policy, and the precise confidence anchors defined in
LABEL_SCHEMA.json are actually present and referenced consistently across every doc that should
carry them -- and that stale wording that conflated "strong" and "critical" tiers (the original
miscalibration this rubric revision fixes) hasn't crept back in.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent

REQUIRED_DECISION_RULES_HEADERS = [
    "## Signal taxonomy",
    "### Weak",
    "### Strong",
    "### Critical",
    "## Scam/Fraud boundary",
    "## Evidence sufficiency gate",
    "## Conflict policy",
    "## Confidence (1-5), precisely",
]

# Wording that conflates the "strong" and "critical" tiers, or otherwise implies a single
# confirmed reused image alone is sufficient for scam_fraud. Presence of any of these in the
# canonical docs is a regression, not a style nitpick.
BANNED_PHRASES = [
    "one flag is strong enough alone",
    "one flag is strong enough to stand alone",
]


def check_label_schema_structure(schema: dict) -> list[str]:
    errors: list[str] = []

    taxonomy = schema.get("signal_taxonomy")
    if not taxonomy or not all(tier in taxonomy for tier in ("weak", "strong", "critical")):
        errors.append("LABEL_SCHEMA.json: signal_taxonomy missing or missing a weak/strong/critical tier")

    conf = schema.get("confidence_scale", {}).get("anchors", {})
    if not all(str(i) in conf for i in range(1, 6)):
        errors.append("LABEL_SCHEMA.json: confidence_scale.anchors missing one or more of 1-5")

    if not schema.get("scam_fraud_boundary_rule", {}).get("rules"):
        errors.append("LABEL_SCHEMA.json: scam_fraud_boundary_rule.rules missing or empty")

    if not schema.get("evidence_sufficiency_gate", {}).get("rule"):
        errors.append("LABEL_SCHEMA.json: evidence_sufficiency_gate.rule missing")

    if not schema.get("conflict_policy", {}).get("rules"):
        errors.append("LABEL_SCHEMA.json: conflict_policy.rules missing or empty")

    return errors


def check_doc_contains_sections(text: str, required_headers: list[str], doc_name: str) -> list[str]:
    return [f"{doc_name}: missing required section {h!r}" for h in required_headers if h not in text]


def check_no_stale_phrases(text: str, banned_phrases: list[str], doc_name: str) -> list[str]:
    return [f"{doc_name}: contains stale/conflating phrase {p!r}" for p in banned_phrases if p in text]


def run_all_checks(workspace: Path = WORKSPACE) -> list[str]:
    errors: list[str] = []
    g = workspace / "annotation" / "guidelines"

    schema = json.loads((g / "LABEL_SCHEMA.json").read_text(encoding="utf-8"))
    errors.extend(check_label_schema_structure(schema))

    decision_rules = (g / "DECISION_RULES.md").read_text(encoding="utf-8")
    errors.extend(check_doc_contains_sections(decision_rules, REQUIRED_DECISION_RULES_HEADERS, "DECISION_RULES.md"))
    errors.extend(check_no_stale_phrases(decision_rules, BANNED_PHRASES, "DECISION_RULES.md"))

    evidence_rules = (g / "EVIDENCE_RULES.md").read_text(encoding="utf-8")
    for term in ("weak", "strong", "critical", "DECISION_RULES.md"):
        if term not in evidence_rules:
            errors.append(f"EVIDENCE_RULES.md: does not reference {term!r}")

    canonical_guide = (g / "ANNOTATION_GUIDE.md").read_text(encoding="utf-8")
    for term in ("DECISION_RULES.md", "Signal tiers", "evidence sufficiency gate"):
        if term.lower() not in canonical_guide.lower():
            errors.append(f"annotation/guidelines/ANNOTATION_GUIDE.md: does not reference {term!r}")
    errors.extend(check_no_stale_phrases(canonical_guide, BANNED_PHRASES, "annotation/guidelines/ANNOTATION_GUIDE.md"))

    top_level_guide = (workspace / "ANNOTATION_GUIDE.md").read_text(encoding="utf-8")
    if "annotation/guidelines/ANNOTATION_GUIDE.md" not in top_level_guide:
        errors.append("top-level ANNOTATION_GUIDE.md: does not point to the canonical guide")
    if len(top_level_guide.splitlines()) > 40:
        errors.append(
            "top-level ANNOTATION_GUIDE.md: grew past 40 lines -- it must stay a short pointer, "
            "not a duplicate of the canonical guide (this is the exact drift this check exists to catch)"
        )

    label_definitions = (workspace / "annotation" / "label_definitions.md").read_text(encoding="utf-8")
    errors.extend(check_no_stale_phrases(label_definitions, BANNED_PHRASES, "annotation/label_definitions.md"))
    if "DECISION_RULES.md" not in label_definitions:
        errors.append("annotation/label_definitions.md: does not reference DECISION_RULES.md")

    worked_examples = (workspace / "annotation" / "examples" / "worked_examples.md").read_text(encoding="utf-8")
    for marker in ("Example F", "Example G", "Example H", "Example I", "Example J", "Example K"):
        if marker not in worked_examples:
            errors.append(f"worked_examples.md: missing {marker}")
    if "never `scam_fraud`" not in worked_examples and "never scam_fraud" not in worked_examples:
        errors.append("worked_examples.md: missing an explicit 'two weak indicators never equal scam_fraud' example")

    for schema_file in (workspace / "annotation" / "annotation_schema.json", g / "pilot_schema.json"):
        text = schema_file.read_text(encoding="utf-8")
        if "LABEL_SCHEMA.json" not in text:
            errors.append(f"{schema_file.relative_to(workspace)}: confidence note does not reference LABEL_SCHEMA.json")

    return errors


def main() -> int:
    errors = run_all_checks(WORKSPACE)
    if errors:
        print(f"FAILED: {len(errors)} guideline-consistency problem(s)")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: guideline layer is internally consistent (taxonomy, boundary rule, sufficiency gate, "
          "conflict policy, and confidence anchors all present and cross-referenced; no stale wording found).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
