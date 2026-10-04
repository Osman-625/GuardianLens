# Evidence Rules — What to Write in Each Field

The Pass 1/Pass 2 output schema (`LABEL_SCHEMA.json`'s `pilot_output_columns`) splits evidence
into three typed fields instead of one free-text `evidence_reason`. This file defines what
belongs in each, and how those fields connect to the signal taxonomy and evidence sufficiency
gate defined in `DECISION_RULES.md`.

## Tag the signal tier, not just the observation

For every signal you cite in `evidence_text`, `evidence_image`, or `evidence_behavioral`, name
its tier (**weak** / **strong** / **critical**) per `DECISION_RULES.md`'s taxonomy, not just what
you saw. This is what lets `reason` and the label follow mechanically from the evidence instead
of being a separate free judgment. Bad: "reused image, looks suspicious." Good: "reused image,
manually confirmed against the other listing -- this is a STRONG signal per DECISION_RULES.md,
not sufficient alone for scam_fraud without a second signal."

## `evidence_text`

Cite the specific phrase or field value from `title`/`description`/`condition`/`price`/
`location_*`/`language`, and its tier. Quote or closely paraphrase. Bad: "description sounds
off." Good: "description says 'must transfer deposit via personal bank transfer before meetup, no
exceptions' -- this is a CRITICAL signal (explicit advance-payment-outside-platform instruction
in the listing's own text, per DECISION_RULES.md's critical-tier examples)."

## `evidence_image`

Describe what you actually saw across the listing's images, and — if `reused_image_indicator`
was true — whether you personally opened the other listing and confirmed the match, and how many
other listings share the image (one match = strong; three or more = critical, per
`DECISION_RULES.md`). Bad: "images look stock." Good: "primary image is the exact manufacturer
product shot; manually opened the one other listing the near-duplicate audit flagged and
confirmed identical crop and lighting for a differently-described 'unique' item -- this is a
STRONG signal (single confirmed match), not critical, so it does not alone justify scam_fraud."
Also note here whether the **image evidence channel counts toward the evidence sufficiency
gate** (i.e. `image_count >= 1` and you actually opened and assessed the photo(s)) — state
`image_count=0` explicitly when true, since that channel then contributes nothing to a
`legitimate` call.

## `evidence_behavioral`

Cite the specific seller-behaviour field values, including explicit nulls/zeros as evidence, not
absence of evidence, and note whether this channel counts toward the evidence sufficiency gate
(at least one of the four fields non-NULL). Bad: "seller seems new." Good: "account_age_days=2,
seller_rating=NULL, review_count=0 (explicit zero, not missing), active_listing_count=14 — many
listings from a 2-day-old account with no rating history. This is a WEAK signal on its own
(common pattern among genuine new sellers too) but the behavioural channel counts as having
content for the sufficiency gate."

## `insufficient_evidence_reason`

Required whenever `label = insufficient_evidence`. State exactly what information, if it existed,
would have let you decide, and — when the reason is the evidence sufficiency gate rather than
conflicting evidence — say so explicitly. Bad: "not enough info." Good: "evidence sufficiency
gate not met: image_count=0 (no image channel) and all four seller-behaviour fields NULL (no
behavioural channel) — only the text channel had content, which alone isn't enough per
DECISION_RULES.md's evidence sufficiency gate, even though nothing in the text itself was
suspicious."

## `reason`

A one-line summary of the overall call, referencing the specific rule applied from
`DECISION_RULES.md`'s "Scam/Fraud Boundary," "Evidence Sufficiency Gate," or "Conflict Policy"
sections as applicable (e.g. "single confirmed strong signal (reused image), no corroboration ->
suspicious per boundary rule #2" or "two weak indicators only, no strong/critical -> suspicious
per boundary rule #1, never scam_fraud" or "critical signal (explicit credential request) alone
-> scam_fraud per boundary rule #5").

## Confidence

Set `confidence` per `LABEL_SCHEMA.json`'s `confidence_scale` anchors and
`DECISION_RULES.md`'s confidence table -- it must follow from the signal tier and corroboration
level cited above, not be a separate free judgment. If `reason` documents conflicting evidence
(per the conflict policy), `confidence` must be 1-2; it is a direct error to document a conflict
and then record confidence 4-5.

## Fields that remain required regardless of label

`listing_id`, `label`, `confidence`, `reason`, `annotator`, `annotator_version`, `timestamp` are
required for every row. `evidence_text`/`evidence_image`/`evidence_behavioral` may be left blank
only for the specific evidence type genuinely absent from that listing (e.g. no seller-behaviour
fields populated at all) — never left blank because it was skipped. When a channel is blank
because it's genuinely empty (not skipped), that blankness itself is the evidence for the
sufficiency gate — say so in the relevant field or in `insufficient_evidence_reason`.
