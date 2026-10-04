# Worked Examples

**ILLUSTRATIVE ONLY.** These are hypothetical scenarios written to demonstrate
reasoning quality -- they do not describe, name, or judge any real listing in this
dataset. GuardianLens has no ground-truth fraud labels; do not treat any of these as
a template to copy onto a specific `listing_id`.

## Strong (valid) reasoning

### Example A -- `suspicious`, confidence 3
> "Two independent signals: (1) `reused_image_indicator=true` and a manual check of
> the images/ folder confirms the primary photo is pixel-identical to another
> listing in this dataset for a different item at a different price -- a genuine
> seller wouldn't re-use a competitor's exact photo. (2) `seller_rating` and
> `review_count` are both NULL and `account_age_days` is 3. Neither signal alone
> would be enough, but together they're a concrete, named pattern, not a vibe."

Why this is strong: cites two *specific, checkable* signals, explains why each is
relevant, and is honest that confidence is moderate (3/5), not maximal.

### Example B -- `insufficient_evidence`, confidence 2
> "Price is within the normal category range, images are unique to this listing,
> but `account_age_days`, `seller_rating`, `review_count`, and `active_listing_count`
> are all NULL -- there is no seller-behaviour signal at all, and the text gives no
> other clue either way. I cannot distinguish a legitimate new seller from a fresh
> scam account from this evidence alone."

Why this is strong: explicitly names which evidence is missing and why that gap
prevents a confident call, rather than defaulting to `legitimate` just because
nothing looks obviously wrong.

## Weak (invalid) reasoning -- do not do this

### Example C -- weak `scam_fraud` claim
> "Price seems too low, feels like a scam."

Why this is weak: no comparison to an actual category price range, no seller or
image evidence cited, "feels like" is not an observable signal. Low price alone
never justifies `scam_fraud` per `ANNOTATION_GUIDE.md`.

### Example D -- weak `legitimate` claim
> "Looks like a normal listing."

Why this is weak: doesn't cite what was actually checked (images? seller fields?
text?). This is indistinguishable from not having looked at all.

### Example E -- weak `suspicious` claim
> "Grammar is bad and seller has no reviews, definitely suspicious."

Why this is weak: both cited signals are explicitly called out in
`ANNOTATION_GUIDE.md` as insufficient on their own (poor grammar is common among
genuine sellers; missing reviews describes most new accounts). Stacking two
individually-insufficient signals without explaining why they combine to mean
something is still weak reasoning -- explain the combination, don't just list flags.

## Signal-tier boundary examples

These specifically demonstrate the weak/strong/critical taxonomy and the exact
scam_fraud boundary from `../guidelines/DECISION_RULES.md`. Each pair shows the
*correct* label and the *wrong* label someone might jump to.

### Example F -- one confirmed strong signal, correctly capped at `suspicious`, confidence 3

> "reused_image_indicator=true. Manually opened the one other listing the
> near-duplicate audit flagged and confirmed the primary image is pixel-identical,
> used there for a different item at a different price. This is a STRONG signal
> (one confirmed match) per DECISION_RULES.md. Nothing else about this listing is
> unusual -- seller_rating=4.8, review_count=112, account_age_days=640, price is
> within category range, description is specific and detailed. Per the Scam/Fraud
> Boundary (rule #2), a single confirmed strong signal alone is `suspicious`, not
> `scam_fraud`, without a second independent signal."

**Label: `suspicious`, confidence 3.** The wrong call here is `scam_fraud` at
confidence 4-5 -- that's exactly the miscalibration this taxonomy exists to prevent:
treating a single confirmed reused image as automatic proof of fraud. A long, clean
seller history is not itself corroboration for escalating -- it's evidence *against*
escalating.

### Example G -- one confirmed strong signal + one weak signal, correctly escalated to `scam_fraud`, confidence 4

> "Same confirmed reused image as Example F (STRONG, one match, manually verified).
> In addition: account_age_days=1, seller_rating=NULL, review_count=NULL,
> active_listing_count=9 (nine listings posted from a one-day-old account with zero
> rating history) -- a second, independent signal. Per Scam/Fraud Boundary rule #3,
> one confirmed strong signal plus one additional independent signal is `scam_fraud`."

**Label: `scam_fraud`, confidence 4.** Note what changed from Example F: not the
reused-image evidence itself (still just one confirmed match, still STRONG, not
critical) but the addition of a second, independent signal. The label followed the
*count and tier* of independent signals, not a gut read of "this feels worse."

### Example H -- one confirmed critical signal alone, correctly `scam_fraud`, confidence 5

> "Description states verbatim: 'Please transfer RM50 booking deposit to my personal
> Maybank account first, no exceptions, then we arrange meetup' -- an explicit
> advance-payment-outside-platform instruction in the listing's own text. This is a
> CRITICAL signal per DECISION_RULES.md (maps directly to a known scam mechanism, no
> plausible innocent explanation for demanding an unescrowed personal transfer before
> any handover). No corroboration needed -- Scam/Fraud Boundary rule #5."

**Label: `scam_fraud`, confidence 5.** No second signal was needed or cited -- a
confirmed critical signal is sufficient alone. Compare to Example F: the reused-image
case needed a second signal to reach this label; a genuine critical signal does not.

### Example I -- two weak indicators, correctly `suspicious` (never `scam_fraud`), confidence 2

> "Two weak signals stack: (1) price is 40% below category median with no reason
> given, (2) account_age_days=5, seller_rating=NULL, review_count=NULL -- brand-new
> account, high-value item, no other seller signal. Neither is unusual alone (new
> accounts and discounted prices are both common for genuine sellers), but together
> they form a specific, named pattern. No strong or critical signal is present --
> per Scam/Fraud Boundary rule #1, any number of weak signals alone caps at
> `suspicious`. This is `suspicious`, not `scam_fraud`, no matter how many more weak
> indicators like these were added."

**Label: `suspicious`, confidence 2.** This is the direct answer to "do two weak
indicators equal scam_fraud?" -- no. Adding a third or fourth weak indicator (e.g.
missing location, generic description) would still not cross into `scam_fraud`
without a strong or critical signal.

### Example J -- evidence sufficiency gate not met, correctly `insufficient_evidence` despite zero red flags

> "image_count=0 (no image channel). account_age_days, seller_rating, review_count,
> active_listing_count all NULL (no behavioural channel). Only the text channel has
> content: a two-line generic description with no specific detail. Per the Evidence
> Sufficiency Gate, `legitimate` requires at least two of the three channels to have
> real content -- here only one does. Nothing in the text is actually suspicious, but
> there isn't enough to check to support `legitimate` either."

**Label: `insufficient_evidence`, confidence 2.** The wrong call is `legitimate` --
"I didn't find anything wrong" is not the same claim as "I checked enough to be
confident nothing is wrong." Compare to Example B (existing, above): same underlying
principle, now backed by an explicit, countable gate instead of an informal read.

### Example K -- confirmed strong signal amid an otherwise-clean profile, conflict policy applies

> "reused_image_indicator=true, manually confirmed against one other listing -- STRONG
> signal. Everything else about this listing looks clean: seller_rating=4.9,
> review_count=340, account_age_days=1200, price in range, detailed description. Per
> the Conflict Policy, any confirmed strong or critical signal rules out `legitimate`
> even amid otherwise-clean evidence -- the floor is `suspicious`. This is the same
> situation as Example F, phrased to emphasize the conflict-policy angle rather than
> the boundary-rule angle: a long clean history does not override one confirmed
> strong signal back down to `legitimate`."

**Label: `suspicious`, confidence 3.** The wrong call is `legitimate` "because the
seller has such a good track record" -- a confirmed strong signal is never waived
away by unrelated positive evidence; it sets a floor, not a suggestion.
