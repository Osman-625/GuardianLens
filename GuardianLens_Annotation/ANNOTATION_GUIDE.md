# GuardianLens Annotation Guide

**This file is a pointer, not a duplicate.** The canonical, current annotation guide is
`annotation/guidelines/ANNOTATION_GUIDE.md` — read it first. Keeping the full guide in exactly
one place, rather than two copies that can drift out of sync, is a deliberate fix: an earlier
version of this file duplicated the canonical guide's content and fell out of date when the
canonical copy was updated with the formal signal taxonomy (weak/strong/critical), the scam/fraud
boundary rules, the evidence sufficiency gate, and the conflict policy (see
`reports/annotation_workflow_audit.md` and `docs/superpowers/plans/2026-09-17-three-pass-ai-human-annotation.md`
for why). This file exists only so `ANNOTATION_GUIDE.md` resolves from the workspace root, as
referenced by older tooling (`annotation/annotation_schema.json`'s `guide_doc` field,
`scripts/verify_annotations.py`'s default schema).

## Where things live

- **Canonical guide (read this):** `annotation/guidelines/ANNOTATION_GUIDE.md`
- **Signal taxonomy, scam/fraud boundary, evidence sufficiency gate, conflict policy, confidence
  anchors:** `annotation/guidelines/DECISION_RULES.md` and `annotation/guidelines/LABEL_SCHEMA.json`
- **What to write in each evidence field:** `annotation/guidelines/EVIDENCE_RULES.md`
- **Worked examples:** `annotation/examples/worked_examples.md`
- **Original (still-valid) label criteria, phrased for the older `annotation_schema.json` column
  shape:** `annotation/label_definitions.md`

## If you only remember one thing

A single confirmed strong signal — including one manually-verified reused image — supports
`suspicious`, not `scam_fraud`, on its own. See `DECISION_RULES.md`'s "Scam/Fraud Boundary" for
the full rule set.
