# Label Definitions

GuardianLens has **no ground-truth fraud labels**. These listings are real, scraped
marketplace listings, not a pre-labeled fraud dataset. The four labels below describe
an annotator's evidence-based judgment, not a verified fact. `insufficient_evidence`
is a first-class, expected outcome -- use it whenever the evidence genuinely doesn't
support a confident call.

## `legitimate`

The listing's text, images, and seller-behaviour fields are consistent with a normal,
good-faith sale. No observable red flags, or only weak/explainable ones (e.g. a new
seller account with no other red flags is common and not on its own suspicious).

**Requires:** no unexplained anomaly across price, images, or seller behaviour, **and**
the evidence sufficiency gate is met -- at least two of the three evidence channels
(text, image, behavioural) must have real, checkable content. A listing with almost
nothing to check (e.g. no images and no seller-behaviour data) cannot be called
`legitimate` just because nothing looks wrong -- see `insufficient_evidence` below and
`../guidelines/DECISION_RULES.md`'s "Evidence Sufficiency Gate."

## `suspicious`

At least one concrete, observable red flag that a genuine seller normally wouldn't
show, but not enough combined evidence to call it fraud outright. This covers both:
(a) two or more **weak** signals stacking into a named pattern, and (b) a single
**strong** signal on its own — e.g. a *manually confirmed* reused image (one other
listing, checked, same photo, different "unique" item), a price notably below the
category's typical range with no explanation, or urgency-pressure language with
nothing else. **A single strong signal never escalates past `suspicious` on its own**
— see `../guidelines/DECISION_RULES.md`'s signal taxonomy and Scam/Fraud Boundary for
the exact weak/strong/critical distinction this label definition assumes.

**Requires:** at least one specific, named signal, tagged with its tier (weak/strong),
in the evidence fields -- never "it just feels off."

## `scam_fraud`

Reached one of three ways: (1) one confirmed **critical** signal alone (e.g. an
explicit request for OTP/PIN/bank credentials, or the same exact images appearing
across **three or more** unrelated seller listings for different "unique" items — a
classic marketplace-scam pattern); (2) one confirmed **strong** signal plus at least
one more independent signal; or (3) two independently confirmed strong signals. **A
single confirmed strong signal alone — including a single confirmed reused image
matched against only one other listing — is `suspicious`, not `scam_fraud`.** Full
definitions and the complete boundary rule: `../guidelines/DECISION_RULES.md`. This
label is still an annotator's judgment call, not a confirmed report -- say so plainly
in the evidence fields and keep `confidence` honest.

**Requires:** cite every signal used with its tier, and explain why they combine (or
why one critical signal alone suffices) to outweigh innocent explanations.

## `insufficient_evidence`

The available fields/images genuinely don't support any of the above with reasonable
confidence -- e.g. the evidence sufficiency gate isn't met (fewer than two of the three
evidence channels have real content), or conflicting signals that don't resolve per
the conflict policy. This is not a weak version of `legitimate`; it means "I cannot
tell," which is honest and useful.

**Requires:** state in `evidence_reason` specifically what evidence would have let you
decide (e.g. "no seller_rating/review_count available and images show nothing
unusual").

---

## What is NOT sufficient evidence on its own (weak-tier signals)

- Low price alone
- Missing seller fields alone (many legitimate new sellers have no history)
- Poor grammar / language mixing alone (very common in genuine MY marketplace listings)
- An *unverified* `reused_image_indicator=true` flag (could be a manufacturer stock
  photo used legitimately by multiple honest sellers of the same product model)

Any of these **combined with another independent signal** can support `suspicious` --
but never `scam_fraud` by themselves, and never in isolation. See
`../guidelines/DECISION_RULES.md`'s signal taxonomy for the full weak/strong/critical
classification (a *manually confirmed* reused image is a stronger case than this list
-- it's `suspicious` on its own, not merely "insufficient," but still short of
`scam_fraud` without a second signal) and `ANNOTATION_GUIDE.md` for the full reasoning
framework and required warnings.
