# Code map

A short guide to where things live and how to change them safely. The README has the setup steps; this file explains how the parts fit together.

## One check, from click to result

1. **Capture (extension).** A click on the toolbar icon runs `extension/entrypoints/background.ts`, which calls `runCaptureForTab` (`extension/lib/capture/runner.ts`). That injects `extension/entrypoints/capture.ts`, which reads the page with `lib/capture/listing.ts`, `seller.ts`, `images.ts` and `classify.ts`. The outcome is written to session storage.
2. **Review (side panel).** `extension/entrypoints/sidepanel/PanelApp.tsx` follows the stored capture through `lib/panel/controller.ts` and `reducer.ts`. The buyer edits a draft (`lib/panel/draft.ts`) in `views/ReviewView.tsx`.
3. **Submit.** `lib/panel/check.ts` prepares the photos (`photos.ts`), posts the form with the client in `shared/src/api.ts`, then polls the status.
4. **Score (API).** `api/routers/assess.py` validates the upload (`api/services/images.py`, `language.py`), scrubs contact details (`privacy.py`) and starts `api/services/orchestrator.py`. The three signals come from `pipelines.py` (test mode) or `trained_models.py` and `trained_visual.py` (trained models). Results are stored by `api/repositories/assessments.py` (SQLite).
5. **Show.** The panel's `views/ResultView.tsx` and the website's `/assess/[id]` page render the same shared components (`shared/src/components`). "See full explanation" opens the website with the session in the address (`shared/src/claim.ts`, `frontend/lib/useSessionClaim.ts`).

The manual form (`frontend/app/assess/page.tsx`) joins at step 3 and sends `source=manual`.

## Where things live

| Folder | What it holds |
| --- | --- |
| `api/` | FastAPI service: routers (HTTP), services (checks and scoring), repositories (storage), models and schemas (data shapes), `dependencies.py` (session and origin checks). |
| `shared/src/` | Code used by both the website and the extension: wording (`copy.ts`), design tokens and component styles (`styles.css`), components, the API client, types, limits. |
| `extension/` | Browser extension (WXT): `entrypoints/` (background, capture script, side panel), `lib/capture/` (page reading), `lib/panel/` (panel state and the check). |
| `frontend/` | Next.js website: `app/` (pages and page styles), `components/`, `lib/`. |
| `scripts/` | Developer tools: launchers, the secret scan, the prose check, the timing script. |
| `docs/` | Specification, deviations (`CHANGES_FROM_SPEC.md`), evidence, audits. |

## How to change common things

| Change | Where |
| --- | --- |
| Any buyer-facing sentence | `shared/src/copy.ts` first; page-only text in the page file; API text in `api/services/orchestrator.py`, `pipelines.py`, `trained_models.py`. Update the tests that quote it. |
| The names of the three checks | `SIGNAL_NAMES` and `SIGNAL_LOOKS_AT` in `shared/src/copy.ts`, and `STAGES` for the stage list. |
| Show or hide model names | `SHOW_MODEL_DETAILS` in `shared/src/copy.ts` (off). |
| Colours, type, radius | The tokens at the top of `shared/src/styles.css`; page layout only in `frontend/app/globals.css` and `extension/entrypoints/sidepanel/panel.css`. |
| An input limit (photos, text length) | `shared/src/limits.ts` and the matching setting in `api/settings.py`. |
| A new marketplace field | Capture in `extension/lib/capture`, the draft in `lib/panel/draft.ts`, the form body in the same file (`buildForm`), the API schema in `api/schemas.py`. |
| Stub or trained scoring | `GUARDIANLENS_INFERENCE_MODE` in `.env`. The API tests always force stub mode. |

## Quality gates

| Gate | Command | Protects |
| --- | --- | --- |
| Format, lint, types | `npm run format:check`, `npm run lint`, `npm run typecheck` | Consistent, type-safe TypeScript. |
| Unit tests | `npm test`, `pytest` | Behaviour of every module; the Python suite never loads the models. |
| Browser tests | `npm run test:e2e -w extension` | The built extension: manifest permissions, capture to result to handoff, layout. |
| Python checks | `ruff check api scripts`, `mypy api` | Style and strict types. |
| Security | `npm audit --omit=dev --audit-level=high`, `python scripts/secret_scan.py` | Known vulnerabilities in shipped packages; committed secrets. |
| Prose | `python scripts/check_prose.py` | The punctuation rule for documents. |

## Conventions

- Every file starts with a header comment; every exported function, type and component has a doc comment; tests say which behaviour they pin and carry a comment per group.
- A comment describes what the code does today. Change the comment in the same edit as the code.
- Format with Prettier (`npm run format`) before commenting; Python is formatted with `ruff format`.

## Known limits worth knowing

- `api/repositories/assessments.py` and the rate limiter assume one server process; several processes need shared storage.
- Two test files read locally recorded real pages and skip themselves when none exist (`extension/fixtures/README.md`).
- The trained text model shows single words as reasons ("pro", "yang"): that is the model, not the interface.
