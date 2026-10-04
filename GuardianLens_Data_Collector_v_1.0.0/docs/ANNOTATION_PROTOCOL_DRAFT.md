# GuardianLens annotation protocol — draft for review

This is a future handoff protocol, not an annotation implementation. The collector
workspace remains for collection and quality review. No labels, annotation tables,
train/test splits or models are created by this stage.

## 1. Freeze and custody

Identify a generation by its snapshot ID and manifest SHA-256. Verify every manifest
entry before use. Membership is exactly `listings.status='approved'` in that frozen
database. Join `images.listing_id = listings.listing_id`; retain the original UUIDs.
Later approvals belong to a later generation. Never silently refresh an existing
annotation input. Maintain a separate annotation workspace and separate storage.

The entire backup is private. Transfer only a reviewed minimum package. Keep
credentials, seller URLs, raw captures, screenshots, AI outputs and review notes
under restricted access. The public metadata index is not a publication approval.
Review pixels for faces, names, contact details, addresses, plates and watermarks;
review text for names, usernames, phone numbers, emails and precise locations.
Any later redaction must create a derivative with its own checksum and provenance;
retain original bytes privately. Do not use private evidence as model input by default.

## 2. Verify all approved records before annotation

Assign every approved UUID to a human quality reviewer in the separate workspace.
Inspect the frozen record viewer and per-record verification report. Automated gate
passes establish structural validity only; they do not establish factual accuracy.
For every field record `supported`, `contradicted`, or `unverifiable`, with reviewer,
time, frozen evidence path, checksum, and precise text span/image region. These are
proposed future quality decisions, not labels assigned by this freeze.

Check title, description, category, condition, price/currency, state/city, language,
all four seller metrics, product-image ownership and image/text correspondence.
Compare all AI attempts, manual edit before/after values, approval actions and state
history. A successful extraction or an approval is not independent corroboration.
An older nonempty AI value does not establish truth; repeated missing AI values do
not prove the source omitted the field. Review automatic approvals and NULL-to-zero
edits explicitly. Never replace missing metrics with zero or another inferred value.

For account age, require a seller-account creation date/age and capture time; record
rounding uncertainty. For ratings and review counts, confirm the values describe
that seller, not the marketplace app, product, or overall platform. Mudah values
such as 4.7 and 200,000 are review triggers, not automatic corrections. For active
listing counts, distinguish total seller inventory from only visible captured cards.
For zero prices, verify whether free, negotiation, instalment or placeholder pricing.

When evidence is absent or insufficient, mark the proposed downstream decision as
unverifiable and keep the record pending downstream. Do not change its collection
approval or source values from this process. Escalate verified corrections through
the collector's existing quality-review procedure only as separately authorized work;
then create a new snapshot. Do not edit this frozen generation.

## 3. Duplicate and association review

Review exact byte hashes, stored difference hashes, source URLs/marketplace IDs,
metadata signatures and description reuse. Stored product-image deduplication may
have suppressed later associations, so a missing association is not proof of unique
imagery. Preserve duplicate/near-duplicate warnings and any recorded counterpart IDs.
Do not infer fraud from image reuse, shared descriptions, low price or missing metrics.
Record relationships separately downstream; never merge UUIDs or invent missing links.
No grouping or dataset splitting occurs in this stage.

## 4. Define fraud labels before assigning them

The project owner must approve an operational fraud definition, evidence standards,
time horizon and allowed evidence sources. Listing content alone often cannot prove
seller intent or completed fraud. Use an explicit insufficient-evidence outcome;
do not force a binary fraud/non-fraud choice. Collection status, mechanical quality
findings and model/extractor outputs must never become fraud ground truth.

Proposed workflow after that approval: two independent annotators review each case
without seeing each other's decisions. Each proposed label needs evidence references
and a written rationale. A third reviewer adjudicates disagreements. Run a pilot
in the separate workspace, compare disagreement by class/platform/language, revise
the written rubric, and repeat the pilot before scaling. Establish acceptance
criteria prospectively; report class counts and agreement with the applicable
denominators. Do not tune criteria retrospectively to hide difficult cases.

## 5. Provenance and release gate

Proposed downstream decision fields: snapshot ID, listing UUID, rubric version,
reviewer pseudonym, decision time, quality decision, evidence references, rationale,
independent decisions and adjudication outcome. This document creates no such table.
Keep source features, quality decisions and eventual target labels distinguishable.
The release owner must sign off evidence quality, unresolved cases, privacy review,
duplicate-association limitations and rubric agreement before any training begins.

Decisions for your review: approve this separation of workspaces; define the fraud
rubric/evidence threshold; nominate independent reviewers and an adjudicator; set
pilot size and agreement criteria. No annotation is authorized or started here.
