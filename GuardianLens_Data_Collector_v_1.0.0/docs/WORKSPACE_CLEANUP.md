# Workspace cleanup — 2026-09-11

This change preserves collection, extraction, review, export, API, database, and
extension behavior. No schema migration or production data operation is part of it.

## Checkpoint and preservation

- Original branch: `main`, two commits ahead of `origin/main`.
- Existing work was extensively modified and untracked before cleanup.
- Backup source commit: `cb4d98a8df5c7a611a8b18816760bbd005e811f7` on
  `backup/workspace-cleanup-20260911`. A separate Git index preserved the current
  branch and staging area.
- Local checkpoint: `.tmp/workspace-cleanup-20260911/`. It contains the original
  status, binary patches, source copies, hashes, deletion checks, and test results.
- Data, credentials, environment files, local task state, verification reports, and
  captured-page fixtures were not added to the backup commit. A credential-shaped
  string in `tests/test_annotation_dataset.py` triggered the scanner, so that file
  was preserved as a local source copy instead.
- No reset, checkout, clean, stash, or recursive deletion was used. The existing
  deletions of the Conda requirements scratch file and OpenRouter module predate
  this cleanup.

## Cleanup classification

| Candidate | Classification | Action and evidence |
| --- | --- | --- |
| 201 `.pyc` files in the root, `src/guardianlens`, `scripts`, and `tests` cache directories | Safe to delete | Exact file names had no references in application imports, config, scripts/build tooling, API/path handling, database/dataset code, tests, or docs. These are compiled caches; maintained `.py` source remains. Each file's hash and resolved workspace path was checked before individual deletion. |
| Four corresponding `__pycache__` directories | Safe to delete | Removed individually only after confirming each was empty. |
| Dashboard markup | Safe to move | Split into adjacent template partials; existing element IDs and API paths retained. |
| `.pytest_cache` | Needs review | Directory access was denied; it was not removed. Its contents could not be verified. |
| Old `.tmp` trees and reports | Needs review | Some contain databases, datasets, screenshots, environment files, or credentials. Preserved. |
| `scripts/_verify_*.json` (11 files) | Needs review | May contain real collection evidence. Preserved in place and ignored by Git to prevent accidental commits. |
| `.qodo`, `.claude/scheduled_tasks.lock`, `dist/guardianlens_release.zip` | Needs review | Purpose, ownership, or archival value is uncertain. Preserved. |
| `data/`, `logs/`, databases and sidecars, backups, replay inputs, exports, images, screenshots, environment files | Must keep | Production/runtime or potentially real user data. No cleanup writes, moves, or deletions. |
| Source, configuration, scripts, extension, documentation, test fixtures, `.venv`, `node_modules` | Must keep | Active project structure, dependencies, or verification inputs. |
| All `.gitkeep` files | Must keep | Runtime/release markers preserve expected directory structure. Backup/test markers are part of preserved evidence trees. No `.gitkeep` files removed. |

The per-file removal list and reference checks are recorded in
`.tmp/workspace-cleanup-20260911/removed.json` and `deletion-reference-checks.json`.
The cache cleanup removed 3,409,388 bytes. No data or source directories were moved.

## Repository map

| Location | Purpose |
| --- | --- |
| `src/guardianlens/*.py`, `schema.sql` | Backend, domain logic, database definitions |
| `src/guardianlens/templates/` | Server-rendered pages and reusable partials |
| `src/guardianlens/static/` | Browser behavior and styles |
| `extension/` | Chrome capture extension |
| `config/` | Collection categories and platform targets |
| `scripts/` | Maintenance, verification, and release commands |
| `tests/` | Automated checks and fixtures |
| `docs/` | Protocols, workflow documentation, verification reports |
| `data/` | Runtime databases, private evidence, images, exports, reports, backups |
| `logs/`, `.tmp/`, `dist/` | Logs, local working/checkpoint artifacts, release output |

This structure already matched `AGENTS.md`; broad directory moves would have added
path risk without improving organization.

## Dashboard organization and data

- `dashboard.html`: page composition and visible approved/platform/review metrics.
- `_dashboard_collection.html`: CSV/manual inputs and capture progress.
- `_dashboard_operations.html`: batch processor, attention agent, operational queue,
  lifecycle log, provider selection, and local tools.
- `_dashboard_coverage.html`: exact status counts, planner, category coverage, and
  review timing.
- `_dashboard_macros.html`: reusable native `<details>` disclosure component.

Collection and processing controls remain available. Secondary details and logs
start collapsed; import instructions open automatically when there is no batch.
Disclosure choices persist in tab session storage without persisting form values.
Polling updates values without replacing disclosures, forms, or unchanged log rows.
Tables scroll within their sections on small screens.

Hardcoded initial replay/processing zeroes are replaced by stored counts. Initial
phase/status labels use a loading state until the stored server snapshot is rendered
through the same JavaScript functions used for subsequent polls. Agent/recovery
status is initialized from that snapshot too. A missing run or batch legitimately
has zero counts; unavailable metrics display `No data`. A failed or timed-out poll
shows an explicit disconnected notice and retains the last stored snapshot, with
automatic retry and a manual refresh button. Requests do not overlap.

Approved/status/activity/review counts remain SQL-backed. Planner targets come from
configuration and are goals, not claimed collection statistics. No frozen-dataset
card was present in the starting template; the referenced freeze/backup modules and
documents remain intact.

## Verification

All mutations during testing use isolated databases and paths. No real marketplace
capture or paid AI request was used to verify this cleanup.

| Check | Result |
| --- | --- |
| Full pytest suite in an isolated source copy, with all source fixtures present | **340 passed, 7 failed**, one existing Starlette/httpx deprecation warning; 148.36 seconds |
| Pre-cleanup comparison of migration, processor/review, and release tests | **25 passed, the same 7 failed**; 26.65 seconds |
| Focused dashboard, API, replay, and attention checks in the working source | **69 passed**, including two new initial-state/empty-state regression tests |
| `python -B scripts/self_test.py` | PASS; includes JavaScript syntax, configuration, required directories, and a temporary database/schema check |
| `python -B scripts/mock_integration_check.py` | PASS; synthetic Carousell and Mudah captures both reached approval in an isolated runtime |
| Browser startup and dashboard rendering at `127.0.0.1:8876` | PASS against an isolated database; no application console errors during checks |
| Existing collector at its configured `127.0.0.1:8770` | PASS; health `ok`, dashboard HTTP 200, initial stored counts equal `/api/dashboard/status`; read-only check |
| Browser manual URL import | PASS; two fixture URLs persisted as two queued rows and remained correct after reload; no marketplace pages were opened |
| Collapse, refresh, and reload | PASS; section state and form contents survived polling; disclosure choices survived reload |
| Narrow viewport | PASS; no document overflow after layout settled, tables scroll inside their panels |
| Disconnect and reconnect | PASS; failed refresh explicitly marked the last snapshot, preserved the two stored rows, then recovered after restart |
| `node --check` for browser/extension scripts | PASS |
| Prettier check for `src/guardianlens/static` | PASS |
| Prettier check including `extension` | Existing formatting warnings in its four files; extension files were preserved byte-for-byte |
| `git diff --check` | PASS |
| Source preservation check | No preserved source files missing; only intended cleanup/dashboard/documentation/test files changed; staging area and current branch unchanged |

The final compatibility adjustment constructs the initial JSON snapshot directly
from the existing template context, leaving backend code unchanged. The 69 focused
tests passed again afterward (23.76 seconds). The running collector also served the
new template successfully without a backend restart.

The full suite was run from `.tmp/workspace-cleanup-20260911/verification-source`
using the existing project Python environment, `-B -m pytest -q -o addopts=''`
and `-p no:cacheprovider`, with its basetemp outside that source copy. This avoids
repeated release-tool traversal of the working repository's old runtime trees.
The first copy omitted HTML test fixtures because it followed the release
allowlist; those fixtures were restored in the verification copy before the final
347-test run. The actual project fixtures were never changed.

### Existing failures preserved

- `test_v5_database_migrates_to_paced_seller_retry_schema_and_preserves_rows`
- `test_missing_seller_signal_goes_needs_attention_and_cannot_approve`
- `test_partially_missing_seller_signal_blocks_approval`
- Four release tests: allowlist/empty structure, runtime injection rejection,
  fresh-release synthetic checks, and required Windows entry points. The existing
  credential-shaped assertion string at `tests/test_annotation_dataset.py:589`
  triggers the release secret scanner.

These failures also occur in the preserved starting source. They were left intact
to keep migration and approval behavior outside this cleanup. No release ZIP was
overwritten or published.

Raw results and the complete final Git status are in the local checkpoint:
`pytest-final.txt`, `pytest-baseline-comparison.txt`, `pytest-live.txt`, and
`git-status-final.txt`. The final focused rerun is `pytest-final-dashboard.txt`.

## Final Git state

`main...origin/main [ahead 2]`; the user's original modified/untracked source and
two pre-existing deletions remain. Cleanup changes are uncommitted. The separate
backup branch holds the checkpoint. No preserved source file is missing and the
staging area matches its original state. The eleven local verification JSON files
still exist, but are now ignored. The source manifest was regenerated for the
current source, including the new dashboard partials and this report; release
packaging remains blocked by the pre-existing scanner finding described above.
