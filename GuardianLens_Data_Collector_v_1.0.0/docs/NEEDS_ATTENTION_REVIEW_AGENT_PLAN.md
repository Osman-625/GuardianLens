# Needs-attention review agent plan

Status: proposed; implementation and production runs have not started.

## Goal and proposed operating mode

Build an in-app background worker that checks every `needs_attention` listing,
fills or corrects fields when captured evidence supports the change, and explains
what still needs capture or human judgment. Provide a one-pass run and an optional
watch mode for newly eligible or changed records, with Start, Pause, Resume, and
Stop controls.

The recommended first version prepares records for final human review. It does
not approve or reject records. Agent activity must be distinguishable from human
review sessions and corrections.

## Current evidence

Read-only production database snapshot inspected on 2026-09-07:

| Observation | Listings |
| --- | ---: |
| Needs attention, total | 1,214 |
| Mudah / Carousell | 834 / 380 |
| Unresolved missing-field warnings | 882 |
| Unresolved near-duplicate image warnings | 230 |
| Unresolved exact duplicate-image warnings | 154 |
| Unresolved image-skipped warnings | 84 |
| Unresolved PII warnings | 74 |
| Eligible under current Mudah seller-retry selection predicates | 830 |

Warning counts overlap. Eligibility does not imply that a retry will succeed.
Of these records, 832 have no seller screenshot path recorded; actual file and
text availability still need validation. Missing values also include seller
rating on 883 records and location state on 222, which existing processing
warnings do not fully describe.

Relevant existing behavior:

- `dashboard.review_queue_snapshot()` exposes at most 100 rows. The worker must
  use a dedicated database scan with stable pagination to cover the whole bucket.
- `processor.py` and `review.py` disagree on required fields. Final approval also
  requires location state, seller rating, and review count. Readiness must use the
  same data requirements as approval, while keeping the human-session gate separate.
- `seller_retry.py` already implements scoped Mudah seller recovery, browser
  leases, pause/resume, pacing, retries, and cooldowns. Success moves a listing to
  `captured`; AI preprocessing is currently a separate operation.
- Seller-retry preparation currently selects all eligible rows, and preprocessing
  uses an item limit rather than an exact list of IDs. Targeted orchestration needs
  explicit item selection before a small pilot can be reliable.
- Full preprocessing replaces extracted fields, warnings, and image records.
  Targeted field repair must preserve unrelated evidence and human corrections.

## Implementation sequence

### 1. Shared validation and complete inspection

Extract reusable, read-only validation from processing and approval. Return
structured findings with a stable reason code, affected field or asset, evidence
availability, and suggested next action. Separate data validation from requirements
for an active human review session.

Check all required listing and seller fields, placeholders, types/ranges,
configured categories, privacy rules, actual image files and metadata, and
duplicate relationships. Treat historical warnings as clues; evaluate the current
record and retain historical findings for audit.

Add a read-only inspection mode that snapshots every eligible listing ID, including
records beyond the first 100. Group actions into repair from existing evidence,
capture recovery, and human review. A record may need several actions.

### 2. Durable worker and audit records

Add `attention_agent.py` for orchestration and a focused shared validation module.
Add a versioned database migration for run, item, and field-change records. Store
status, attempts, retry time, lease, input revision/evidence fingerprint, findings,
outcome, and field-level before/after values with evidence references and extraction
provider/model/prompt version where applicable.

Claim bounded work transactionally; recheck status and input version before writing.
Skip records under human review or whose state has changed. Resume safely after
restart, bound retries across runs, and avoid repeating attempts on unchanged inputs
that already produced no progress. Watch mode must back off when idle or failing.

Keep agent events separate from human `review_actions`, timing statistics, and
human-correction provenance in dataset generation. Store scrubbed evidence references
without copying raw private captures into logs or exported datasets.

### 3. Evidence-supported field repair

Use captured listing/seller text first and screenshots as corroboration or an
unambiguous fallback. Reuse provider adapters and the extraction contract; request
targeted field proposals rather than reprocessing the entire listing.

Allow recovery of visible missing values, obvious configured-category mappings,
supported numeric normalization, and the contract's capture-date-based account-age
derivations. Each proposed change needs an evidence reference and explanation.
Treat marketplace content as data, never as instructions to the agent.

Leave absent values null. Zero is valid only when evidence shows zero. Do not guess
seller ratings, reviews, locations, condition, or description. Preserve prior human
corrections and route conflicting evidence to human review.

Apply allowed changes, metadata-signature updates, warning resolutions, and status
changes atomically after validation. Preserve original extraction and audit history.
Only resolve findings that have been verified as fixed. Send a record to
`ready_for_review` only when data blockers and unresolved attention issues are cleared;
otherwise retain `needs_attention` with specific remaining actions. Readiness is
checked again at eventual human approval because duplicates can change over time.

### 4. Capture recovery and unresolved issues

Integrate the existing seller-retry manager for its currently supported Mudah
scope. Add exact listing-ID selection, exclude existing active recovery jobs, and
enforce a cumulative retry budget so new batches cannot reset exhausted attempts.
Keep its browser lease, pacing, and CAPTCHA/access cooldowns authoritative.

Coordinate recovery and extraction as separate persisted stages: complete or stop
seller capture before starting an exact-ID extraction pass. Reuse the existing
mutual exclusion with URL replay and preprocessing. Prefer targeted seller-field
extraction after recovery so unrelated fields and images remain intact. Record new
capture timestamps and preserve provenance when live evidence differs from the
original capture.

Route unsupported recovery cases, unavailable listings, missing product images,
exhausted attempts, unresolved privacy issues, and duplicate-image decisions to an
actionable human queue. The agent may apply existing deterministic privacy scrubbing
and recheck the result; ambiguous or damaging redactions remain human decisions.
It must not silently delete images, choose duplicate winners, or approve conflicts.

### 5. Dashboard and review integration

Add a Needs attention agent panel with Inspect all, Start repair, Pause, Resume,
Stop, and optional Watch for new records controls. Support exact selected IDs,
platform/reason filters, bounded item/time/API-call limits, and progress for inspected,
changed, ready, awaiting capture, awaiting human review, and failed records.

Show each record's blockers, before/after changes, evidence references, and next
action in the existing review detail page. Clearly distinguish agent edits from
human edits. Protect mutations with the existing local token checks. Document new
configuration in `.env.example` and `README.md`.

### 6. Verification and rollout

Use temporary databases, synthetic captures, and mocked extractors to verify:

- complete coverage beyond 100 records and shared processing/approval data rules;
- supported repairs versus missing evidence, especially zero versus unknown;
- image integrity, privacy, category, and duplicate gates;
- stale inputs, concurrent human edits, and protected final states;
- atomic writes, retry limits, idempotency, pause/resume, and restart recovery;
- exact-ID recovery/extraction and exclusion of other active workers;
- distinct agent/human audit records and unchanged human review statistics.

Run affected regression tests, the full pytest suite, repository self-test and
appropriate audits; check formatting and visually verify the dashboard changes.
After implementation, inspect the whole bucket without applying repairs, then run
a 25-record pilot with available evidence. Inspect its field diffs and unresolved
reasons before expanding to bounded batches and a separate seller-capture pass.

## Definition of done

Every listing selected for a run has a persisted result: prepared for human review,
awaiting capture, awaiting a named human decision, exhausted/failed with a reason,
or skipped because it changed state. Supported repairs have traceable evidence and
pass shared validation. Repeating a completed run does not duplicate edits or spend
calls on unchanged unresolved records. The UI makes remaining work actionable, and
final human approval continues to enforce all existing gates.
