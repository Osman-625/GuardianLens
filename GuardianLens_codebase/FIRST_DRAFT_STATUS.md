# First Draft Status

**Generated from:** `Pre_implementation docs.zip`

**Build classification:** Product and architecture first draft. Development-stub mode only.

## Completed and verified in the generation environment

| Area | Result | Evidence |
| --- | --- | --- |
| Archive inspection | All eight supplied Markdown files extracted and read | Copied unchanged to `docs/spec/` |
| FastAPI contract | Submission, status, result, cancel, feedback, history, development admin, and export routes created | `api/routers/` |
| Privacy controls | PII scrub, image re-encoding, raw inference text clearing, uploaded byte clearing after processing | `api/services/` |
| Ownership control | Cross-session result access returns a generic not-found response | Automated test |
| Missing-signal rule | No seller data becomes unknown, not suspicious | Automated test |
| Unsupported language rule | Chinese-dominant text returns a structured field error | Automated test |
| Python tests | 9 passed | `pytest -q` |
| Python syntax | Passed | `python -m compileall -q api ml scripts` |
| Secret scan | Passed | `python scripts/secret_scan.py` |
| Prose dash check | Passed | `python scripts/check_prose.py` |

## Created but not fully verified in the generation environment

| Area | State | Reason and required action |
| --- | --- | --- |
| Next.js dependency graph | Exact direct versions are pinned in `frontend/package.json` | The sandbox could not resolve the npm registry. Run `npm install`, commit the generated lockfile, then run lint, type checking, and build. |
| Supabase migrations | Drafted from document 05 | No Supabase CLI or Postgres server was available. Apply to a disposable project and inspect policies before use. |
| Supabase adapter | Boundary exists but intentionally raises an error | Confirm P-2, then implement and integration-test it. |
| Admin authentication | Development token only | Replace with Supabase Auth and `profiles.role = 'admin'`. |
| Real model serving | Interfaces and bundle schema only | Train and archive the five required artefact groups, then build a real loader. |
| Latency evidence | Harness exists | Supply a real adapter. Stub output is marked invalid for NFR-02. |
| User-study materials | Drafts with blockers stated | Close O-3 and O-4, obtain supervisor approval, then finalise. |

## Integrity decisions

1. No marketplace scraper, crawler, URL fetcher, OCR pipeline, browser extension, Facebook Marketplace support, community reporting, or guaranteed-fraud feature was added.
2. No research listing, label, adjudication, participant, consent, trial, or questionnaire row was generated.
3. No F1 score, calibration result, latency claim, user-study result, or risk-band threshold was presented as real evidence.
4. Development scores carry the bundle label `dev-stub-unvalidated` and a permanent warning.
5. Supabase remains the committed production database. The in-memory repository is restricted to stub development and automated tests.

## First implementation priority

Complete GL-P0-02 by installing frontend dependencies on a connected machine, generating the lockfile, and running the frontend checks. Then validate the SQL migrations in a disposable Supabase project and implement the real repository adapter before any real user or research data enters the application.
