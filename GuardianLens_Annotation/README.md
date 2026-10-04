# GuardianLens Annotation Workspace

A standalone workspace for the human fraud-risk annotation phase of the GuardianLens
FYP project. Built from a read-only, independently-audited export of the approved
listings in the GuardianLens Data Collector's database -- **the source collector
repository was never modified to build this workspace** (verified: `git status`
before/after every read/export step was byte-identical).

## Where the data came from

- Source: `GuardianLens_Data_Collector_v_1.0.0/data/collector.sqlite3`, read strictly
  read-only (`mode=ro` SQLite URI) via `scripts/_dbutil.py`.
- Source-repo images read from `data/images/<platform>/<listing_id>/...`, copied
  into this workspace and SHA-256-verified after copy.
- Snapshot taken: 2026-09-13 (live database, not a stale prior export).

## Counts

- **Source approved listings:** 2,209 (`status='approved'` in the source DB) --
  1,410 Carousell / 799 Mudah.
- **Annotation-ready:** 2,209 (100% -- the source's own 9-point atomic-approval gate
  already enforces required fields, image presence, and PII scrubbing before a
  listing can reach `approved`; this workspace's *independent* re-audit, using its
  own separately-implemented checks rather than importing the source's code, found
  zero listings that failed image integrity, structural, or hard-fail checks).
- **Excluded:** 0 (none -- see `data/excluded/` structure, kept ready for future
  batches where this may not be 0).
- **Images copied:** 10,970, every one SHA-256-verified against the source's stored
  hash both immediately after copy and again by `scripts/verify_images.py`.

Full numbers: `reports/dataset_validation_report.md` and
`reports/dataset_validation_summary.json`.

## What was found (and what was/wasn't fixed)

- **0** duplicate listing IDs, marketplace IDs, source URLs, or metadata signatures
  among approved listings (re-verified independently, not just trusted from the
  source DB's own constraints).
- **6** possible-repost candidate groups (same platform+title+price) -- reported,
  not auto-excluded; see the validation report.
- **174** cross-listing near-duplicate image groups (265 listings touched) -- a real
  reused-image signal, pre-populated into `listings.csv`'s `reused_image_indicator`
  column for annotators to investigate. (A separate, much larger set of
  *within-listing* near-duplicates -- i.e. a listing's own multiple photos of the
  same item -- was found and correctly excluded from this signal; that's expected,
  not a finding.)
- **418 currency values normalized** in this copy only (`"RM"` -> `"MYR"`) -- source
  DB left untouched; see `reports/redactions_applied.csv`.
- **14 listings** matched an "address-hint" PII pattern; manually reviewed and judged
  to be legitimate public meetup-location mentions (malls, plazas, named streets --
  standard content for arranging a marketplace meetup in Malaysia), not personal home
  addresses, so **not redacted** -- redacting them would have destroyed useful,
  non-sensitive annotation context for no privacy benefit. No email, phone, or
  social-handle PII was found in any of the five scanned text fields across all 2,209
  listings.
- **No fraud/scam-judgement field exists anywhere in the source schema** -- nothing
  to strip for label leakage beyond what's already excluded below.

## What is deliberately NOT in this workspace

- Screenshots, `data/private/**`, `.env`, `local_token.txt`,
  `ai_provider_override.txt`, provider API keys, raw AI `structured_output` JSON,
  full audit-trail JSON columns (`human_corrections_json`, `review_audit_json`,
  `status_history_json` -- audit-only, not model-facing).
- **Nothing sensitive is stored here at all** -- there is no private/ folder, because
  nothing private was ever copied in the first place.

## Folder structure

```
GuardianLens_Annotation/
├── README.md                    -- this file
├── ANNOTATION_GUIDE.md           -- pointer only; canonical guide is annotation/guidelines/ANNOTATION_GUIDE.md
├── requirements.txt              -- Python deps (Pillow)
├── data/
│   ├── annotation_ready/
│   │   ├── listings.csv / listings.jsonl
│   │   ├── images_manifest.json  -- {relative_path: sha256} for every copied image
│   │   └── images/<platform>/<listing_id>/...
│   ├── excluded/
│   │   ├── excluded_listings.csv
│   │   └── exclusion_reasons.csv
│   └── reference/
│       ├── category_mapping.csv, platform_mapping.csv, schema.json
├── annotation/
│   ├── annotation_schema.json, annotation_template.csv, label_definitions.md  -- original schema, still valid
│   ├── guidelines/     -- CANONICAL: ANNOTATION_GUIDE.md, LABEL_SCHEMA.json, pilot_schema.json,
│   │                      DECISION_RULES.md, EVIDENCE_RULES.md
│   ├── pilot/           -- Pass 1: 120-listing Claude vs Codex blind pilot
│   ├── runs/full_v1/    -- Pass 2: full-dataset Claude/Codex annotation (populated once the pilot passes)
│   ├── review/          -- Pass 3: human review tool output
│   └── examples/worked_examples.md
├── rules/, scripts/rule_engine/, scripts/run_rule_annotation.py  -- rule engine (3rd independent
│   reference only -- see reports/annotation_workflow_audit.md). Unchanged by this task.
├── archive/legacy_annotation_workflows/  -- retired dual-human pilot/templates, never run,
│   kept for provenance. See its README.md.
├── scripts/
│   ├── _dbutil.py, _piiscan.py           -- shared read-only helpers
│   ├── validate_dataset.py                -- needs --source-repo (re-audit from source)
│   ├── export_annotation_dataset.py       -- needs --source-repo (rebuild the export)
│   ├── verify_images.py                   -- workspace-only, no source-repo needed
│   ├── verify_annotations.py              -- schema-driven; pass --schema for the pilot/full-run shape
│   ├── select_pilot_sample.py             -- validates the 120-listing pilot sample is still live
│   ├── compute_agreement.py               -- kappa/confusion-matrix/severe-disagreement between any two annotation files
│   ├── compute_consensus.py               -- joins Claude + Codex + rule engine per listing
│   ├── build_human_review_queue.py        -- Pass 3 P0-P4 prioritized queue (3-way consensus)
│   ├── build_review_queue.py              -- rule-engine-ONLY triage queue (single source; not the Pass 3 queue)
│   ├── finalize_labels.py                 -- applies the documented finalization policy
│   ├── verify_final_dataset.py            -- pre-freeze integrity checklist
│   ├── freeze_dataset.py                  -- writes data/final_labeled/ (refuses while any row is unresolved)
│   ├── build_splits.py                    -- leakage-safe train/val/test/clean_validation, seed 42
│   └── final_integrity_check.py           -- workspace-only, no source-repo needed
├── docs/
│   ├── DATASET_SPLIT_SAFETY.md
│   └── superpowers/plans/                 -- 2026-09-14 rule-engine plan (frozen) +
│                                              2026-09-17 3-pass AI+human annotation plan
└── reports/
    ├── annotation_workflow_audit.md       -- Stage A audit this task's cleanup is based on
    ├── dataset_validation_report.md / dataset_validation_summary.json
    ├── per_listing_validation.json
    └── redactions_applied.csv
```

## Setup

```
pip install -r requirements.txt
```

## Running validation / verification

```
# Only these two need the source repo (to re-derive the export from scratch):
python scripts/validate_dataset.py --source-repo "<path to GuardianLens_Data_Collector_v_1.0.0>"
python scripts/export_annotation_dataset.py --source-repo "<path to GuardianLens_Data_Collector_v_1.0.0>"

# These three run against THIS workspace only -- no source repo needed:
python scripts/verify_images.py
python scripts/verify_annotations.py
python scripts/final_integrity_check.py
```

## Starting annotation (current workflow -- 3-pass Claude + Codex + rule engine + human review)

The original two-human-annotator workflow described in earlier versions of this README was
never run and has been retired -- see `reports/annotation_workflow_audit.md` and
`archive/legacy_annotation_workflows/`. The active workflow is:

1. **Pass 1 -- 120-listing blind pilot.** Claude and Codex independently annotate the pilot
   sample (`annotation/pilot/pilot_listing_ids.csv`) via the `run-ai-annotation-pilot` skill.
   Read `annotation/guidelines/ANNOTATION_GUIDE.md` first.
2. **Kappa gate.** `python scripts/compute_agreement.py --a annotation/pilot/claude_pilot.csv --b annotation/pilot/codex_pilot.csv`
   -- kappa >= 0.61 to proceed (see `annotation/pilot/README.md`).
3. **Pass 2 -- full-dataset AI annotation.** Same dispatch, all annotation-ready listings, once
   the pilot passes. Writes `annotation/runs/full_v1/claude_annotations.csv` /
   `codex_annotations.csv`. The rule engine (`output/weak_annotations.csv`, already generated) is
   the third independent reference -- run `python scripts/run_rule_annotation.py` only if it
   needs regenerating (e.g. after a rules/*.yaml change; see the `run-rule-annotation` skill).
4. **Consensus.** `python scripts/compute_consensus.py --claude ... --codex ... --out ...`
5. **Pass 3 -- human review.** `python scripts/build_human_review_queue.py --consensus ...`
   produces the prioritized `reports/human_review_queue.csv` (P0-P4). A human reviews and records
   `human_final_label` per row.
6. **Finalize.** `python scripts/finalize_labels.py --consensus ... --reviewed ... --out ...`
7. **Verify + freeze.** `python scripts/verify_final_dataset.py --final ...` then
   `python scripts/freeze_dataset.py --final ...` (writes `data/final_labeled/`, refuses while
   any row is still `unresolved`).
8. **Splits.** `python scripts/build_splits.py --final ...` (leakage-safe, seed 42). No model
   training happens in this workflow.

Full detail: `annotation/guidelines/ANNOTATION_GUIDE.md`'s "Workflow" section.

## How annotations should be saved

Claude/Codex pilot and full-run output CSVs are edited in place by the dispatching agent session
(see the `run-ai-annotation-pilot` skill), never by hand-editing `listing_id` or other pre-filled
columns.

## Privacy

Nothing private is stored here (see above) -- there is no private data to protect
inside this workspace by construction, not by redaction after the fact.

## What's model-training-facing vs audit-only

`data/annotation_ready/listings.csv` + the eventual `final_label.csv` are what a
future model-training pipeline should consume. `reports/` and
`data/reference/schema.json`'s `_excluded_by_design` list are audit-only context for
humans, not inputs to any model.

## What must not be changed manually

- `data/annotation_ready/listings.csv`, `.jsonl`, and `images_manifest.json` --
  regenerate via `export_annotation_dataset.py` instead of hand-editing.
- The `listing_id` and `reused_image_indicator` columns in any annotation template.
- Anything under `reports/` -- these are audit outputs, not editable data.

## Dataset split safety

See `docs/DATASET_SPLIT_SAFETY.md` before creating any future train/val/test split --
this dataset has known near-duplicate/repost groupings that must not be split across
train and test.
