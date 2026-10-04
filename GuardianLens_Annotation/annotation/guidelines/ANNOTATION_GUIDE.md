# GuardianLens Annotation Guide (canonical)

This is the canonical, current copy of the annotation guide. The top-level
`ANNOTATION_GUIDE.md` is a short pointer to this file. If the two ever disagree, this file wins.

## Objective

You are producing evidence-based, human judgment labels for real Malaysian marketplace
listings (Carousell / Mudah.my), to support later development of a fraud-risk signal.
**There is no ground truth.** GuardianLens never collected confirmed fraud reports -- these are
ordinary scraped listings. Your label is a documented judgment call from observable evidence, not
a verified fact. That is expected and fine; the honesty of your reasoning matters more than being
"right."

This applies identically whether the annotator is a human reviewer, Claude, or Codex: cite
specific, checkable evidence, never guess, and use `insufficient_evidence` whenever the evidence
genuinely doesn't support a confident call.

## One annotation unit

One row = one `listing_id`. Evaluate together, as a single unit:
- All text fields in `data/annotation_ready/listings.csv` for that `listing_id` (title,
  description, condition, price, currency, location, category, language).
- All images in `data/annotation_ready/images/<platform>/<listing_id>/`.
- The seller/behavioural fields: `account_age_days`, `seller_rating`, `review_count`,
  `active_listing_count`.
- The precomputed `reused_image_indicator`.

**Screenshots and private staging text are deliberately NOT included** -- they never leave the
source collector's private storage. Everything needed to make a judgment is in the CSV + images
folder.

## The four labels

See `annotation/label_definitions.md` for full criteria and `LABEL_SCHEMA.json` for the exact
machine-readable vocabulary. Summary:
- **legitimate** -- no unexplained red flag, AND the evidence sufficiency gate is met (see below).
- **suspicious** -- one concrete, named red flag (weak signals stacking, or one confirmed strong
  signal alone), not enough alone for `scam_fraud`.
- **scam_fraud** -- one confirmed critical signal alone, or a confirmed strong signal plus at
  least one more independent signal, or two confirmed strong signals. **A single confirmed strong
  signal by itself -- including a single confirmed reused image -- is `suspicious`, not
  `scam_fraud`.** See "Signal tiers" below.
- **insufficient_evidence** -- the evidence genuinely doesn't support a call, or the evidence
  sufficiency gate isn't met. Use this whenever you'd otherwise be guessing.

**Before doing anything else, read `DECISION_RULES.md` in full.** It is the canonical source for
all four of: the weak/strong/critical signal taxonomy, the exact scam_fraud boundary rules, the
evidence sufficiency gate that must be met before `legitimate`, and the conflict policy for when
signals point in different directions. `EVIDENCE_RULES.md` then covers what counts as citable
evidence per field type, tagged by tier.

## Signal tiers (read `DECISION_RULES.md` for full definitions, examples, and non-examples)

Every signal you observe is **weak**, **strong**, or **critical** -- never treat a signal as
generically "a red flag" without placing it in one of these three tiers, because the tier
determines what label it can support:

- **Weak** (e.g. low price alone, new seller, missing rating, unverified reused-image flag):
  supports `legitimate`/`insufficient_evidence` only -- never `suspicious`/`scam_fraud` alone, no
  matter how many stack.
- **Strong** (e.g. a *manually confirmed* single reused image, urgency language alone, a
  condition/photo mismatch): supports `suspicious` alone; needs one more independent signal to
  reach `scam_fraud`.
- **Critical** (e.g. an explicit credential/OTP request, an explicit advance-payment-outside-
  platform instruction, confirmed reuse across three-plus listings): supports `scam_fraud` alone.

## How to judge textual evidence

Read the whole title + description. Ask: is there a *specific, checkable* anomaly (unrealistic
claims, contact-outside-platform pressure, urgency pressure combined with another flag)? Note it
in the evidence fields with a quote or paraphrase of what you saw. Grammar/language quality is not
evidence on its own (see warnings below).

## How to judge image evidence

Open **every** image in the listing's folder -- not a sample, all of them, regardless of how many
there are. This is not optional: in pilot v2, 2 of the 3 severe (`legitimate` vs `scam_fraud`)
annotator disagreements traced directly to one annotator not opening every image in a 9-12 image
set and missing a single unrelated/unadvertised item photo buried mid-set or near the end -- the
first image or two looking clean and consistent is not evidence that the rest are too. Ask: do
these look like they were taken by the actual seller of this specific item (own background, own
lighting, own imperfections), or do they look like manufacturer/stock photos, or images that don't
match the described condition/model?
`reused_image_indicator=true` means our automated audit found this listing's images perceptually
near-identical to images in a *different* listing elsewhere in the dataset -- open both listings
and compare manually before treating this as meaningful; automated hash matching can have false
positives. If you disagree with the precomputed flag after checking, say so in your notes.

## How to judge seller behaviour

`account_age_days`, `seller_rating`, `review_count`, `active_listing_count` can each be a real
value, a genuine **zero** (extracted as evidence, not assumed), or **NULL/missing** (no evidence
either way). Missing is not suspicious by itself -- many genuine sellers have thin profiles. A
*combination* like "brand-new account + high-value item + zero reviews + no other seller signal
at all" is a real pattern worth naming explicitly; a single missing field is not.

## Reused images -- how to handle

Treat `reused_image_indicator=true` as a prompt to investigate, not a verdict. Actually open the
other listing(s) involved before citing it as evidence -- an unverified flag is only a **weak**
signal. Once manually confirmed (you personally saw the same photo used for a different "unique"
item), it becomes a **strong** signal, per `DECISION_RULES.md`. **A single confirmed reused image,
by itself, is `suspicious`, not `scam_fraud`** -- this is the single most common miscalibration
this guide exists to prevent. It only reaches `scam_fraud` if it's corroborated by another
independent signal, or if the same images turn up across three or more unrelated listings (which
is a **critical** signal on its own).

## Low prices -- how to handle

A price below what you'd expect for the category/condition is worth noting, but only becomes
meaningful combined with something else. Never label `scam_fraud` or even `suspicious` on price
alone.

## Avoiding assumptions

Do not assume: a Malay-heavy or grammatically rough listing is more likely to be fraudulent
(standard, legitimate marketplace language); a missing field means the seller is hiding something
(extraction gaps happen for legitimate listings too); a low `image_count` means fewer photos taken
deliberately to hide flaws.

## Missing data

Never guess a value that isn't there. If the missing data is exactly what would let you decide,
use `insufficient_evidence` and say what's missing.

## Evidence sufficiency gate (before labeling `legitimate`)

`legitimate` requires that at least **two of the three evidence channels** (text, image,
behavioural) have real, checkable content -- not merely be absent. If two or more channels are
empty (e.g. `image_count=0` and all seller-behaviour fields are NULL), "nothing looks wrong"
means there was barely anything to look at, not that the listing is clean -- use
`insufficient_evidence` instead. Full precise definition (what counts as "content" per channel):
`DECISION_RULES.md`, "Evidence Sufficiency Gate."

## Conflicting evidence

If some signals point toward legitimate and others toward suspicious or worse, follow the
conflict policy in `DECISION_RULES.md`: any confirmed strong or critical signal rules out
`legitimate` even amid otherwise-clean evidence (floor is `suspicious`); a genuine standoff with
no way to resolve is `insufficient_evidence`, not a coin flip toward whichever label feels safer.
Document both sides, and set `confidence` low (1-2) whenever the reason itself documents
conflicting evidence -- never pretend certainty you don't have.

## Documenting evidence

Always cite the *specific* field, phrase, or visual observation, and its signal tier (weak /
strong / critical). "Feels off" is never acceptable. See `EVIDENCE_RULES.md` for exactly what
belongs in each output field, including how confidence must follow from the tier and
corroboration you cite -- not be a separate free judgment.

## What annotators must NOT do

- Do not invent or assume values for missing/NULL fields.
- Do not treat any single weak signal (price, grammar, missing seller data, an *unverified*
  reused-image flag) as automatic proof of anything.
- Do not treat a single *confirmed* strong signal (e.g. one manually-verified reused image) as
  automatic proof of `scam_fraud` -- it supports `suspicious` alone; see `DECISION_RULES.md`'s
  Scam/Fraud Boundary for what it takes to escalate.
- Do not skip the evidence fields -- required for every labeled row.
- Do not edit the pre-filled `listing_id`, `reused_image_indicator`, or any other pre-filled
  column.
- Do not look for or use screenshots/private data outside `data/annotation_ready/`.
- Do not discuss or guess at a listing's real-world outcome (e.g. searching for the seller
  online) -- label from the evidence provided in this workspace only.
- **For AI annotators specifically:** do not access, read, or reference any other annotator's
  output file, `output/weak_annotations.csv`, `output/annotation_features.csv`'s rule-derived
  scores, or any file under `reports/` while labeling. You must arrive at your label from
  `data/annotation_ready/listings.csv` + the listing's own images only.

## Required warnings (read before starting)

1. **A low price by itself does not prove fraud.**
2. **Missing seller information by itself does not prove fraud.**
3. **Poor grammar by itself does not prove fraud.**
4. **Reused product images are evidence, not automatic proof** -- verify visually before treating
   `reused_image_indicator=true` as anything more than weak.
5. **A single confirmed strong signal -- including one confirmed reused image -- supports
   `suspicious`, not `scam_fraud`, on its own.** It takes a second independent signal, or a
   critical-tier signal, to reach `scam_fraud`. See `DECISION_RULES.md`'s Scam/Fraud Boundary.
6. **Labels must be based on observable evidence**, documented in the evidence fields, not
   intuition.

See `annotation/examples/worked_examples.md` for concrete strong vs. weak reasoning.

## Workflow (current, 3-pass)

1. **Pass 1 -- 120-listing blind pilot.** Claude and Codex each independently label the 120
   listings in `annotation/pilot/pilot_listing_ids.csv`, writing to `claude_pilot.csv` /
   `codex_pilot.csv` respectively (see the `run-ai-annotation-pilot` skill for the exact
   dispatch procedure). Neither sees the other's output or the rule engine's output.
2. **Kappa gate.** `python scripts/compute_agreement.py --a annotation/pilot/claude_pilot.csv
   --b annotation/pilot/codex_pilot.csv`. Kappa >= 0.61: proceed. 0.40-0.60: revise this guide,
   re-run the pilot as a new version, do not proceed on the old numbers. < 0.40: stop, escalate,
   do not scale up.
3. **Pass 2 -- full-dataset AI annotation.** Once the pilot passes, Claude and Codex each
   independently annotate all annotation-ready listings, writing to
   `annotation/runs/full_v1/claude_annotations.csv` / `codex_annotations.csv`. The rule engine's
   `output/weak_annotations.csv` (already generated, unchanged) is the third independent
   reference.
4. **Consensus.** `python scripts/compute_consensus.py --claude ... --codex ... --out ...` joins
   all three sources per listing.
5. **Pass 3 -- human review.** `python scripts/build_human_review_queue.py --consensus ... `
   produces the prioritized queue (`reports/human_review_queue.csv`). A human reviews P0-P3 rows
   plus the P4 QC sample and records `human_final_label`.
6. **Finalize.** `python scripts/finalize_labels.py ...` applies the documented finalization
   policy (human review wins where present; unanimous Claude+Codex agreement finalizes
   unreviewed rows; everything else stays `unresolved` until reviewed).
7. **Verify + freeze.** `python scripts/verify_final_dataset.py ...` then
   `python scripts/freeze_dataset.py ...` (refuses to freeze while any row is `unresolved`).
8. **Splits.** `python scripts/build_splits.py ...` (leakage-safe, group-aware, seed 42). No
   model training happens as part of this workflow.
