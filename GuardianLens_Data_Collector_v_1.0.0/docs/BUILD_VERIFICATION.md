# Build and Audit Verification Report

Verification date: 2026-08-28
Target: GuardianLens Data Collector v1.0.0
Environment used: `guardianlens-collector`, Python 3.12.13, Node.js 24.18.0

## Readiness boundary

The source and distributable are eligible for the representative live soft test. They are
not certified for a 2,500-record collection campaign until the original manual flow and a
two-platform CSV replay both pass the live Chrome/provider procedure in `README.md` and
`docs/CSV_BATCH_REPLAY.md`.

## Final automated gates

- Python compile/import check: PASS
- Pytest suite: PASS (206 passed; 0 failed; 0 skipped)
- JavaScript syntax: PASS for dashboard, extension service worker, and popup
- Structural self-test: PASS; OS-temporary database only
- Synthetic integration: PASS; one Carousell + one Mudah record approved in an OS-temporary project
- Security/data-integrity regression suites: PASS
- Concurrent duplicate approval and atomic Edit + Approve: PASS
- Concurrent first-start migration: PASS; one durable migration row and `quick_check=ok`
- Crash recovery: PASS, including explicit interrupted-review audit markers, persistent
  replay recovery, stale browser-lease recovery, and lost-acknowledgement reconciliation
- Soft-test database/assets/exports/reports isolation: PASS
- Manifest generation and verification: PASS on the documentation-complete source tree
- Strict-allowlist ZIP verification: PASS; no missing/unexpected files, secret hits,
  forbidden runtime data, or manifest errors
- Fresh-extraction structural self-test and synthetic integration: PASS
- Fresh extracted application startup on an isolated loopback port: PASS

The only test warning is an upstream Starlette `TestClient` deprecation concerning its
httpx integration; it does not indicate an application test failure.

## Five audit passes

### Pass 1 — Functional

Traced manual capture and CSV replay to their shared `CaptureRequest` → normalized provider
extraction → PII and image processing → validation → mandatory review → atomic approval →
approved-only export. Added persistent ordered replay, per-URL diagnostics, bounded retry,
and crash-safe capture reconciliation without adding a second processing pipeline.

### Pass 2 — Data integrity and consistency

Added versioned/validated migrations with pre-migration backups; expanded orphan, file,
hash, duplicate, state-history, review-session, processing-run, cleanup, and soft-test
audits; made counts/planner/export use coherent read snapshots; added full lifecycle search.

### Pass 3 — Adversarial failure and security

Hardened localhost Host/client boundaries, form/API token checks, same-origin private assets,
provider error redaction, bounded retry/backoff, HTTPS image retrieval and SSRF defenses,
safe image re-encoding, atomic filesystem choreography, release secret scanning, and ZIP
path/content verification. An unsafe automatic production-reset utility found during this
pass was removed and regression-protected; production reset is not a shipped feature.

### Pass 4 — Research methodology

Verified that every listing is researcher-supplied, either through the manual extension or
a prepared CSV/pasted URL list. GuardianLens performs no discovery/search/pagination,
AI only fills collection fields, there are no fraud/legitimacy or AI-confidence fields,
approval is human-only, completion is based on approved counts, and private screenshots
never enter ordinary exports.

### Pass 5 — Researcher experience

Added exact live status counts, CSV upload and pasted-URL input, import summaries, current
two-stage replay URL/status, popup/checkpoint visibility, capture controls, explicit retry,
and scoped Process-next-50/60-minute controls,
All Records search/paging, bounded review totals, provenance displays, keyboard/focus/touch
improvements, and partial polling without full-page reloads. Manual capture and manual
processing controls remain available.

## Release hygiene verified by code/tests

The release uses an explicit source allowlist and rejects stale manifests. It excludes:

- `.env` and provider credentials
- collector token/provider override files
- production and soft-test SQLite databases and sidecars
- screenshots, staging material, collected product images, exports, and reports
- logs, caches, bytecode, dependencies, temporary files, and agent/tool state

The ZIP verifier rejects unsafe/duplicate names, symlinks, oversized content, runtime-file
injection, missing required files/directories, manifest mismatches, and secret-like content.
Fresh verification runs self-test, the complete pytest suite, and synthetic integration from
a newly extracted disposable directory.

## Live checks still required

These cannot be certified offline because they require the operator's current Chrome,
marketplace pages, network path, and configured provider account:

1. Manually capture one Carousell Malaysia and one Mudah individual listing.
2. Import and replay a mixed CSV with 10 random listings from each platform.
3. Confirm actual page evidence, seller links, and image URLs remain compatible with the
   current marketplace DOMs in both modes.
4. Confirm capture pause/resume/checkpoint progress, then separately start and monitor the
   scoped preprocessing run in the configured Chrome session.
5. Confirm the selected real provider/model authenticates, extracts the normalized schema,
   and reports quota/model/network failures safely.
6. Review, correct, approve, audit, and export the successful records in soft-test mode.

Do not begin large real collection until all five live checks pass.
