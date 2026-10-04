# Data and Research Boundary

## Collection boundary

The researcher supplies every individual listing, either by opening it and pressing
**Capture Current Listing** or by uploading/pasting a prepared URL list. GuardianLens does
not search, crawl, paginate, discover listing URLs, select listings, or approve records.
CSV replay opens only queued URLs in the configured Chrome session and may open the seller
profile linked by that listing only to preserve the behavioural signal. Manual and replay
captures converge at the same `CaptureRequest`. Replay commits every capture checkpoint before
the operator starts the separate bounded pictures/AI preprocessing stage.

Each import is also materialized as a viewable, formula-safe Stage 1 CSV under
`data/private/replay_batches/<batch_id>/stage_1_urls.csv`. The capture pass verifies this
immutable file against the durable SQLite queue before it claims a URL. Replay batches and
every attempt remain durable SQLite records. CAPTCHA, login, access-denied,
bot-check, deleted, unavailable, timeout, and invalid-listing pages are recorded explicitly;
GuardianLens does not bypass them. Failures are not retried inside the current capture pass or
processing run; an operator may explicitly requeue an eligible failure only afterward.

## Approved research data

Normal approved exports may contain cleaned listing text, platform/category metadata,
research-relevant visible seller behaviour, product-image metadata/references, source
provenance, normalized AI provider/model/prompt provenance, status history, and human
correction/review audit data. Only `approved` records count toward the dataset total.

## Private collection evidence

Listing screenshots and private staging material are capture/review evidence. They live under
`data/private/` in production or `data/soft_test/runtime/private/` in soft-test mode. They
are served only through protected same-origin localhost routes and are never included in
ordinary dataset exports or the release ZIP. Retention follows `SCREENSHOT_RETENTION`.

## Product images

Product images are research assets, not screenshots. They are stored separately under
`data/images/<platform>/<listing_id>/` (or the isolated soft-test equivalent) only after
HTTPS/public-host validation, size/pixel/decode checks, safe metadata-stripping re-encode,
hashing, duplicate checks, and atomic publication.

## Secrets and local runtime data

Provider API keys stay only in `.env`. The independent collector token and provider override
stay under `data/private/`. Databases, WAL/SHM files, logs, screenshots, staging data,
collected images, exports, reports, secrets, caches, and test/tool state are runtime data and
must not enter the distributable ZIP.

## Soft-test isolation

The real two-listing trial uses `GUARDIANLENS_MODE=soft_test`, with a separate database and
separate screenshots, staging, images, temporary files, exports, and reports. Soft-test
records never count toward production targets. The localhost collector token and the
operator's dashboard-selected provider override are shared configuration, not dataset
content; all captured/processed/reviewed data and outputs remain mode-isolated.

## Excluded from this phase

Fraud/legitimate labels, annotation/adjudication, train/validation/test assignments, model
training/evaluation, model predictions, fraud scores, AI confidence, calibrated confidence,
and automatic marketplace discovery belong to later GuardianLens phases.
