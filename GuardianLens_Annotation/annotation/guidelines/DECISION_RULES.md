# Decision Rules

This is the canonical, human-readable reasoning behind the machine-readable rules in
`LABEL_SCHEMA.json` (`signal_taxonomy`, `scam_fraud_boundary_rule`, `evidence_sufficiency_gate`,
`conflict_policy`, `confidence_scale`). If this file and `LABEL_SCHEMA.json` ever appear to
disagree, that is a bug -- report it, don't silently pick one. Every rule below applies
identically to a human reviewer, Claude, and Codex.

## Signal taxonomy

Every observed signal is classified into exactly one of three tiers before it's used in a
decision. Classify the signal itself, not the listing as a whole -- a listing can carry signals
from multiple tiers at once.

### Weak

**Definition:** a common, independently-explainable attribute that a substantial share of
genuine listings/sellers also exhibit. Cannot, by itself, distinguish fraud from ordinary
marketplace variation.

**Examples:** low price vs. category median with no stated reason; a new seller account
(`account_age_days` small); missing or zero `seller_rating`; low `review_count`; missing
`location_city`/`location_state`; unusual or grammatically rough wording; an unusual-but-plausible
condition claim; a generic/templated seller description; `reused_image_indicator=true` that has
**not yet been manually verified**.

**Non-examples (things that look weak but aren't a signal at all):** a low price with an
explicit, checkable reason stated in the description ("selling below market, relocating
overseas") -- an *explained* anomaly is not an anomaly; a new account listing a single low-value
item with nothing else unusual (low stakes, no behavioural anomaly, nothing to weigh); missing
`seller_rating` alongside a long, consistent `active_listing_count` history (the gap is resolved
by other context, not a live gap).

**What weak signals can support alone:** at most `legitimate` (noted) or `insufficient_evidence`.
Weak signals **never** support `suspicious` or `scam_fraud` by themselves, no matter how many
stack -- see "Scam/Fraud Boundary" below.

### Strong

**Definition:** a specific, checkable anomaly that most genuine sellers would not exhibit, with a
plausible-but-uncommon innocent explanation.

**Examples:** a **single confirmed** reused image -- meaning `reused_image_indicator=true` was
manually verified by opening the other listing(s) and visually confirming the same photo is used
for a different "unique" item; urgency-pressure language with no other flag present; a described
condition that visibly contradicts what the photos show; a request to move off the platform's own
messaging/escrow that is paired with pressure, exclusivity, or urgency (e.g. "DM only, do not use
platform chat," "must confirm via WhatsApp right now before I give it to someone else"); one image
within the listing's own photo set that shows a completely different, unrelated, unadvertised item
(not merely a condition mismatch on the advertised item -- the photo is of something else
entirely).

**Non-examples (things that look strong but are actually a different tier):** an *unconfirmed*
`reused_image_indicator=true` you haven't personally checked -- that's still weak until verified;
a request for OTP/PIN/bank credentials -- that's critical, not merely strong (see below); a
single stock/manufacturer photo shared by two listings of the same widely-sold retail product
(plausible non-fraud explanation -- treat as weak/non-signal, not strong, unless something else
makes the match suspicious, e.g. the two listings claim different, incompatible conditions); a
seller sharing a WhatsApp number, Telegram handle, or `wasap.my`-style link **solely to arrange
meetup logistics or answer questions** (pickup time/place, availability), with no pressure,
urgency, or exclusivity language attached -- this is universal, expected practice on Carousell/
Mudah and is not a signal at all (weak or otherwise), not merely a downgraded strong signal. The
distinguishing question is not *"did they mention an off-platform channel"* but *"is there
pressure to abandon the platform's protections specifically"*; an OS/device system-info screen
(e.g. Windows Settings > System > About) reporting a lower RAM/memory transfer speed than the
listing's advertised marketing spec (e.g. "6400 MT/s" shown vs. "8533 MT/s" advertised) when the
device name, processor model, and storage capacity shown in the same screenshot all otherwise
match the listing exactly -- this is a known OS reporting artifact for LPDDR5X/DDR5 modules
(Windows frequently reports a conservative JEDEC/base profile rather than the manufacturer's rated
XMP/AMP speed), not evidence of a different or misrepresented device, unless the *other*
identifying fields (device name, processor, storage) also fail to match.

**What a strong signal supports alone:** `suspicious`, confidence 3-4. **A single strong signal,
by itself, is never enough for `scam_fraud`** -- this is the fix for the most common
miscalibration risk in this schema: *a confirmed reused image is usually a strong signal, not an
automatic scam_fraud verdict.* See "Scam/Fraud Boundary" for what it takes to escalate.

### Critical

**Definition:** a specific, checkable act or piece of content with essentially no plausible
innocent marketplace explanation -- it maps directly onto a known scam mechanism, not merely a
suspicious pattern.

**Examples:** an explicit request for OTP/TAC/PIN/CVV/bank login credentials; an explicit
instruction, stated in the listing's own text, to pay a "deposit"/"booking fee"/"agent fee" via
personal transfer before any handover or platform escrow; **confirmed reused images spanning
three or more unrelated listings** for different "unique" items (not just one other match -- one
match is strong, three-plus is critical); an independently, manually-verified hit against a
rule-engine critical finding (e.g. a Semak Mule match -- note this data source is currently
disabled/NULL project-wide, per `rules/rule_documentation.md`, so this example is unavailable in
practice today, listed here for completeness/future-proofing only).

**Non-examples (things that look critical but aren't):** a single confirmed reused image (that's
strong -- see above, this is the exact case this taxonomy exists to fix); vague urgency language
("must sell today") with no payment-diversion instruction; a generic "no returns" policy; a
seller asking for a phone number to arrange meetup logistics (normal marketplace behaviour, not a
credential request).

**What a critical signal supports alone:** `scam_fraud`, confidence 4-5. No corroboration
required -- one confirmed critical signal is sufficient by itself.

## Scam/Fraud boundary

This is the explicit rule set that resolves ambiguity at the `suspicious` / `scam_fraud` line:

1. **Any number of weak signals alone, with no strong or critical signal present, caps at
   `suspicious`.** Two, five, or ten weak signals stacked together are still `suspicious` at most
   -- never `scam_fraud`. (This directly answers "do two weak indicators equal scam_fraud?" --
   no, not without a strong or critical signal also present, regardless of count.)
2. **One confirmed strong signal alone is `suspicious`, not `scam_fraud`.** This is the reused-
   image case: a single manually-confirmed reused image, with nothing else notable, is
   `suspicious` (confidence 3-4), not `scam_fraud`.
3. **One confirmed strong signal + at least one additional independent signal (weak or strong)
   is `scam_fraud`.** E.g. a confirmed reused image *plus* a brand-new account with zero
   seller-behaviour history is `scam_fraud`.
4. **Two independently confirmed strong signals, even without weak corroboration, is
   `scam_fraud`.** E.g. a confirmed reused image *and* urgency-pressure language, each
   independently verified.
5. **One confirmed critical signal alone is `scam_fraud`, no corroboration required.**
6. **Established seller reputation or history never downgrades the label a confirmed strong or
   critical signal already sets.** A high `seller_rating`, large `review_count`, long
   `account_age_days`, or many `active_listing_count` is behavioural-channel *evidence*, not a
   license to override the boundary rules above -- it is not a countervailing signal that offsets
   a confirmed strong or critical one. A critical signal (e.g. an explicit pay-before-handover
   instruction) is `scam_fraud` regardless of how established the seller looks; a single confirmed
   strong signal is `suspicious` regardless of reputation. Reputation may be cited in `reason` as
   context and may justify not going to the very top of the confidence range (see the confidence
   table below), but it must never move the *label* back toward `legitimate`. Do not reason "this
   seller is too established to be running this scam" -- that is an assumption about outcomes, not
   evidence about this listing's own text/image/behavioural content.

## Evidence sufficiency gate (before `legitimate`)

`legitimate` requires that **at least two of the three evidence channels** -- text, image,
behavioural -- have real, checkable content, not merely be absent. "No red flag found" is not the
same as "evidence of legitimacy" when there was barely any evidence to check in the first place.

- **Text channel has content** when title + description together contain at least one specific,
  checkable detail beyond a generic one-line listing (a condition detail, a specific feature, a
  disclosed reason for the price or sale, etc.).
- **Image channel has content** when `image_count >= 1` and the image(s) were actually opened and
  show the item itself (not just a bare placeholder/manufacturer-only shot with nothing to
  assess).
- **Behavioural channel has content** when at least one of `account_age_days` / `seller_rating` /
  `review_count` / `active_listing_count` is non-NULL. A genuine disclosed zero counts as content
  ("0 reviews" is information); NULL does not.

**If two or more channels lack content** (e.g. `image_count=0` **and** all four seller-behaviour
fields are NULL), do not default to `legitimate` just because nothing looks wrong -- there wasn't
enough to look *at*. Use `insufficient_evidence` and name exactly what's missing in
`insufficient_evidence_reason`.

This formalizes what `annotation/examples/worked_examples.md`'s Example D ("Looks like a normal
listing" -- indistinguishable from not having looked) and Example B (missing seller-behaviour
data + nothing else -> `insufficient_evidence`) were already demonstrating informally.

## Conflict policy

When signals point in different directions:

1. **If any strong or critical signal is present, the label cannot be `legitimate`**, even if
   the rest of the evidence looks clean. The floor is `suspicious`.
2. **If only weak signals conflict with an otherwise-clean profile**, resolve using the evidence
   sufficiency gate and the weak-signal rule above (`legitimate` or `insufficient_evidence` --
   never `suspicious`/`scam_fraud` from weak signals alone).
3. **If evidence is genuinely missing or ambiguous on both sides**, such that neither a positive
   nor a negative case can be made, use `insufficient_evidence`. Never resolve a real standoff by
   picking whichever label feels less alarming -- that's a guess wearing a label, not a judgment.
4. **Always document both the supporting and the conflicting evidence** in the reason/evidence
   fields, regardless of which label you land on.
5. **Confidence must reflect the conflict.** Never record confidence 4-5 when the `reason` field
   itself documents evidence pulling in two directions -- see the confidence anchors below.

## Confidence (1-5), precisely

Confidence is not a separate free judgment call -- it must follow from the signal tier and
corroboration level that produced the label:

| Score | Meaning | Typical trigger |
|---|---|---|
| **1** | Mostly guessing. Evidence is thin, ambiguous, or nearly balanced between two labels. | A real conflict per the conflict policy, or evidence just barely clears the sufficiency gate. |
| **2** | Leaning toward this label, real doubt remains. | At least one plausible alternative label not fully ruled out. |
| **3** | Reasonably confident -- evidence is specific and clear-cut but thin (one signal) or a minor ambiguity remains. | A single confirmed strong signal (`suspicious`), or an ordinary clean `legitimate`/`insufficient_evidence` call. |
| **4** | Confident -- multiple independent signals align, or one confirmed critical signal, no significant counter-evidence. | Strong+weak or strong+strong reaching `scam_fraud`; a critical signal with minor residual doubt. |
| **5** | Very confident -- evidence is unambiguous, directly observed, no credible alternative explanation. | A confirmed critical signal with no conflicting evidence at all; a `legitimate` call where a disclosed explanation is independently corroborated. |

As a rule of thumb: a single strong signal alone should not be scored above 4 (it's `suspicious`,
not `scam_fraud`, so 5 shouldn't come up there at all); a bare "nothing found" `legitimate` call
resting on ordinary review should not be scored above 4 either -- 5 is reserved for cases with
active, corroborating evidence, not merely the absence of a red flag.

## Summary decision table (cross-reference only -- the rules above are authoritative)

| Situation | Label | Confidence guide |
|---|---|---|
| Evidence sufficiency gate not met, no red flag either | `insufficient_evidence` | 1-2 |
| One weak signal, gate met, nothing else | `legitimate` (note the signal) | 3 |
| Two or more weak signals, gate met, no strong/critical | `suspicious` | 2-3 |
| One confirmed strong signal, nothing else | `suspicious` | 3-4 |
| One confirmed strong signal + one more independent signal | `scam_fraud` | 4 |
| Two confirmed strong signals | `scam_fraud` | 4 |
| One confirmed critical signal | `scam_fraud` | 4-5 |
| Any strong/critical signal present alongside otherwise-clean evidence | `suspicious` (floor) | 1-2 |
| Genuinely conflicting/ambiguous evidence, no way to resolve | `insufficient_evidence` | 1 |
| Confirmed strong/critical signal, but seller has strong reputation/history | label per signal tier (unchanged); reputation does not downgrade | per tier, reputation may trim confidence slightly, never the label |

## Version history

- **v1 (2026-09-17):** original guide as used in `annotation/pilot/` (pilot v1, kappa 0.393 vs.
  Codex -- see `reports/` -- failed the `< 0.40` stop-and-escalate gate in
  `annotation/pilot/README.md`, with 5 severe `legitimate`/`scam_fraud` disagreements).
- **v2 (2026-09-21):** revised after diagnosing those 5 severe disagreements. Two rubric gaps were
  found responsible: (1) the "off-platform contact" strong-signal example was being read as
  "any WhatsApp/Telegram mention," rather than only when paired with pressure/urgency/exclusivity
  -- added an explicit non-example for ordinary meetup-logistics contact-sharing (Strong section);
  (2) nothing stated that seller reputation cannot override a confirmed critical/strong signal, so
  the label was misapplied in a case with an explicit pay-before-handover critical signal on an
  otherwise well-reviewed account -- added Scam/Fraud Boundary rule #6. Also added an explicit
  strong-signal example for an unrelated/unadvertised item photo inside the listing's own image
  set. Re-pilot under this version writes to `annotation/runs/pilot_v2/`, not `annotation/pilot/`
  (v1 results are kept, not overwritten).
- **v3 (2026-09-23):** revised after diagnosing pilot v2's result -- kappa 0.496 vs. Codex (up
  from v1's 0.393), but still 3 severe `legitimate`/`scam_fraud` disagreements, each individually
  human-adjudicated (see `annotation/review/pilot_v2_severe_disagreement_adjudication.csv`). Root
  causes were NOT a guideline ambiguity in 2 of 3 cases: one annotator (Codex) failed to open every
  image in a 9-12 image set and missed a single unrelated-item photo (a Galaxy Z Flip in a Galaxy
  S23 listing; a putter in a driver-clubs listing) -- both confirmed correct as `scam_fraud` on
  manual review, matching the annotator (Claude) that had already opened every image. Strengthened
  ANNOTATION_GUIDE.md's "How to judge image evidence" section to make opening every image
  mandatory and non-optional, citing this exact failure mode. The third case WAS a genuine
  guideline gap: a Windows System-Info screenshot showing a lower RAM transfer speed than the
  listing's advertised marketing spec was read by one annotator as a strong photo/spec-mismatch
  signal; this is a known OS reporting artifact for LPDDR5X/DDR5 memory, not evidence of a
  different device, when the device name/CPU/storage all otherwise match -- added as an explicit
  non-example under Strong. All three cases were adjudicated to the label the guideline-compliant,
  every-image-opened annotator had already produced; no further re-pilot was run given project
  timeline constraints -- the fixes target execution discipline and one narrow technical false
  positive, not the label taxonomy itself.
