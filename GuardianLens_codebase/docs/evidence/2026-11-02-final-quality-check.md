# Final quality check, 2 November 2026

One pass over the whole project in its final state: static checks, every unit and browser test, the production build, and a live run of the trained models, the production website and the built extension. The sealed-test accuracy is not part of this check; it is reported in Chapter 4 and 6.

## Result at a glance

| Area | What was run | Result |
| --- | --- | --- |
| Formatting, lint, types | Prettier, ESLint, TypeScript (3 workspaces), ruff, strict mypy (45 files) | Clean |
| Unit tests | Python 189, shared 79, frontend 37, extension 357 (2 real-page files skip until pages are recorded) | 662 passed, 0 failed |
| Browser tests | 6 tests on the built extension (layout, capture to result to handoff, manifest) | 6 passed |
| Build | `next build`, extension zip (179 KB) | Passes, all 8 routes |
| Extension permissions | Built manifest | activeTab, scripting, sidePanel, storage only; no marketplace host; no content scripts |
| Dependencies | `npm audit --omit=dev`, `npm ls` | 0 vulnerabilities shipped; no invalid or missing packages |
| Secrets, prose | Secret scan, punctuation check | Clean |
| Trained stack | Six real validation-split listings through the form, repeated | Same six scores as the first real-use run (82, 85, 75, 53, 86, 62) |
| Accessibility | axe-core (WCAG 2.0 and 2.1 A and AA, best practice) on 5 pages at 375, 768 and 1440 px | 0 violations in 15 combinations |
| Layout | Overflow, headings, console, failed requests, touch targets, keyboard focus (first 12 tab stops) | No findings |
| Links | Every internal link on the landing page, including the extension download | All answer 200 |
| Security and privacy | 15 API checks: cross-site POST, wrong content type, absurd price, non-Latin text, no photo, non-image, session isolation, unknown id, no admin route, markup in a title, contact details, per-minute limit | 15 of 15 pass |
| Word | A copy of the compiled report opened and exported by Word | 126 pages; Figures 4.6 and 4.7 on page 64, 4.8 on page 66, 4.9 on page 67; captions updated |

## Findings, and what to do

| # | Finding | Impact | Action |
| --- | --- | --- | --- |
| 1 | Four checks started at the same moment each took 37 to 39 seconds (alone, a check takes 2 to 5 seconds). | The 10-second budget (NFR-02) holds for one buyer at a time, not for several at once. Matters for a user-study session with parallel participants. | Run study sessions one at a time, or queue scoring on the server; re-time with `scripts/time_checks.py` before the study. |
| 2 | In the regression run the first check took 16.8 seconds; the other five took 2.2 to 4.3 seconds. | One check above the 10-second budget; the cause was not found. | Re-time on a quiet machine after a fresh start. |
| 3 | `npm audit` reports 20 advisories (17 moderate, 3 high) in development tools (`undici`, `zod`, `minimatch` and others). | None ship to buyers. Fixing needs major version bumps of the test tooling. | Leave until after the viva, or fix on a branch. |
| 4 | `pip-audit` is not installed on this machine; CI runs it and it was last run on 10 October. | Python dependency advisories since then are unchecked. | Run it before submission. |
| 5 | The study database holds 60 test assessments (53 manual, 7 extension) and 58 sessions from development and today's checks. | Study records would mix with test records. | Archive or clear `data/guardianlens.sqlite3` before the user study. |
| 6 | Four empty folders in `.tmp` cannot be deleted by a normal account (Windows denies access). | None; they are git-ignored. | Delete them from an Administrator prompt: `takeown /f .tmp /r /d y`, then `rd /s /q .tmp`. |

## Privacy checked in the database

The `assessments` table has a scrubbed title, structured inputs and the result; it has no column for the description text or photo bytes. A byte search of the whole database file found none of the phone number and email address used in the privacy test. The feedback table is empty.

## Not covered

- Code coverage was not measured (no coverage tool is installed).
- The toolbar-icon click and capture from a live marketplace page need a person and a real browser (`docs/superpowers/audits/2026-10-manual-checks.md`).
- Word was checked on a copy; the real report's fields (contents, list of figures) still need Ctrl+A, F9, and the v4 PDF still needs a new export.
- Model accuracy is measured elsewhere; six listings do not measure it.
