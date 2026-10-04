# Pilot Annotation Batch (Claude vs Codex)

**Purpose:** test the annotation schema and `annotation/guidelines/ANNOTATION_GUIDE.md` on a
small batch *before* committing to labeling all 2,209 listings. If Claude and Codex disagree a
lot here, that's a signal to fix the label definitions/guide, not a signal that either annotator
did a bad job. This replaces the original two-human pilot design (see
`archive/legacy_annotation_workflows/dual_human_pilot_v1/`, never run) with two independent AI
annotators; humans enter the process later, at Pass 3 (review), not here.

## Composition (120 listings, seeded/reproducible sample -- recovered, not regenerated)

This is the same 120-listing sample originally drawn for the dual-human pilot in
`GuardianLens_Annotation.zip` (2026-09-13 snapshot), re-validated against the live dataset via
`python scripts/select_pilot_sample.py` (passes as of 2026-09-17 -- 120/120 listing_ids still
live).

- 105 stratified proportionally by (platform, category) from the full 2,209 -- matches the live
  distribution (75 Carousell / 45 Mudah, all 12 categories present).
- **15 deliberately drawn from listings with `reused_image_indicator=true`** -- stress-tests the
  "how to handle reused images" section of the guide.

Full list with platform/category/indicator: `pilot_listing_ids.csv`.

## What to do

1. Read `../guidelines/ANNOTATION_GUIDE.md` first (the canonical copy).
2. Dispatch the Claude track and the Codex track independently, per the `run-ai-annotation-pilot`
   skill (`.claude/skills/run-ai-annotation-pilot/SKILL.md`). Each writes only to its own file:
   `claude_pilot.csv` (already pre-filled with the 120 `listing_id`s and `annotator=claude_pilot_v1`)
   and `codex_pilot.csv` (same, `annotator=codex_pilot_v1`). **Neither track may read the other's
   output file, `output/weak_annotations.csv`, or anything under `reports/` while labeling.**
3. Once both are filled, validate them (use `--schema` -- these files use the new
   `annotator`/`reason` column shape, not the older `annotator_id`/`evidence_reason` shape):
   ```
   python scripts/verify_annotations.py --file annotation/pilot/claude_pilot.csv --schema annotation/guidelines/pilot_schema.json
   python scripts/verify_annotations.py --file annotation/pilot/codex_pilot.csv --schema annotation/guidelines/pilot_schema.json
   ```
4. Compute agreement:
   ```
   python scripts/compute_agreement.py --a annotation/pilot/claude_pilot.csv --b annotation/pilot/codex_pilot.csv
   ```

## Reading the result

- **Cohen's kappa >= 0.61** on `label`: the schema/guide are working reasonably well. Proceed to
  Pass 2 (full-dataset annotation).
- **Kappa 0.40-0.60**: look at the printed disagreement pairs. If most disagreements are
  `suspicious` vs `insufficient_evidence` or `suspicious` vs `legitimate` (adjacent/soft calls),
  that's normal and expected -- proceed, but consider tightening the label definitions for that
  specific boundary.
- **Kappa < 0.40, or any `scam_fraud` vs `legitimate` disagreement** (opposite-end disagreement,
  flagged automatically by `compute_agreement.py` as "severe"): stop and revise
  `annotation/guidelines/ANNOTATION_GUIDE.md` / `DECISION_RULES.md` before scaling up --
  something in the instructions is being read two different ways. Increment the guide/prompt
  version, re-run the full 120-listing pilot as a new version under `annotation/runs/pilot_v2/`
  (do not overwrite `pilot_v1` results), and re-check the gate.

This pilot batch is a subset of `data/annotation_ready/` -- no separate images/data copy was
made; use the same `data/annotation_ready/images/<platform>/<listing_id>/` folders and
`listings.csv` rows referenced by these listing_ids.
