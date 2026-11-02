# GuardianLens FYP2 First Draft

GuardianLens is a multimodal, explainable fraud-risk decision-support prototype for buyers checking Mudah.my and Carousell product listings before payment. This archive turns the supplied pre-implementation documents into a runnable product scaffold while preserving the locked scope and separating development stubs from research evidence.

## Read this first

Inference defaults to `GUARDIANLENS_INFERENCE_MODE=stub`. For the latest trained TF-IDF/text-cues, XGBoost, CLIP/SSCD and calibrated fusion run, see [trained model setup](docs/TRAINED_MODELS.md). Sessions, assessments and feedback are kept in a local SQLite file (see [Data storage](#data-storage)). Trained mode loads saved artifacts and never silently substitutes development scores.

Stub scores are displayed with a permanent warning. They are not CLIP, SSCD, TF-IDF/text-cues, XGBoost, calibrated late-fusion, or SHAP results. They must not be used in Chapter 4 metrics, the user study, a real buying decision, or any claim that GuardianLens has been trained.

## Included

- Next.js and TypeScript source for landing, submission, processing, result, explanation, feedback, and session history.
- FastAPI endpoints matching the proposed `/api/v1` contract.
- Field-level validation, unsupported-script text rejection (Chinese, Tamil, Thai, Arabic and similar), image type and size checks, metadata-stripping re-encoding, PII scrubbing, session ownership checks, feedback, history, rate limiting, and structured error envelopes.
- Development-only five-stage pipeline stubs with explicit missing-signal handling.
- A timing script (`scripts/time_checks.py`) that measures real checks against the running API, for the NFR-02 evidence (10 seconds a check).
- Draft consent, session, and questionnaire materials and a blank study-trial template. No generated labels, participants, or study rows are included.
- Automated backend, shared-package, extension, website and browser tests, CI source, secret scanning, and prose punctuation checks.
- The original eight specification documents under `docs/spec/`.

## Repository map

```text
guardianlens/
  frontend/             Next.js screens S1 to S7
  extension/            Browser extension (WXT): captures a listing on click, result in a side panel
  shared/               Types, API client, design tokens, and components used by the site and the extension
  api/                  FastAPI application and tests
  research/             Study drafts and the study-trial template
  docs/spec/             Supplied pre-implementation documents
  docs/plans/            Build and next-step records
  docs/ch4-notes/        Incremental implementation notes
  scripts/               Local development and verification helpers
```

## Quick start on Windows

Prerequisites: Conda (Anaconda or Miniconda), Node.js 22 or newer, npm, and Git. The conda environment installs Python 3.13 for you (`pyproject.toml` supports 3.12 and 3.13, not 3.14).

### First-time setup

```powershell
cd GuardianLens_codebase
conda env create -f environment.yml
conda activate Guardianlens_venv
npm install
Copy-Item .env.example .env
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

`environment.yml` installs the API, the saved-model serving packages (scikit-learn, XGBoost, torch, transformers), and the test tools. `npm install` at the repository root installs all three JavaScript packages (`shared`, `extension`, `frontend`) as npm workspaces. To update the environment after `pyproject.toml` changes: `conda env update -f environment.yml --prune`.

### Run after setup

Open Anaconda Prompt (or CMD with Conda available) and run:

```cmd
cd /d "C:\Users\cusma\OneDrive\Desktop\FYP Project\04_System_Workspaces\GuardianLens_codebase"
conda activate Guardianlens_venv
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

Leave this terminal open. Wait for both `GuardianLens API ready` and `GuardianLens web ready`, then open [the website](http://localhost:3000). You can use the browser extension once both servers are ready.

Trained models can take a minute to load. Startup output is saved in `.tmp/dev/api.stderr.log`, `.tmp/dev/api.stdout.log`, and the matching `web` logs. If startup fails, the launcher prints the end of the error log. Press Ctrl+C to stop both servers before launching again.

API auto-reload is off by default to avoid repeated model loading when a synced folder reports file changes. Restart the launcher after changing Python code, or opt in with `powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -ReloadApi` (which watches only `api/`).

Open:

- Web: `http://localhost:3000`
- API health: `http://localhost:8000/health`
- OpenAPI: `http://localhost:8000/docs`

## Quick start on Linux or macOS

```bash
cd GuardianLens_codebase
conda env create -f environment.yml
conda activate Guardianlens_venv
npm install
cp .env.example .env
./scripts/dev.sh
```

## Browser extension

The extension captures one listing when you click its icon on a Mudah.my or Carousell listing, lets you review the captured fields, and shows the result in the browser side panel. "See full explanation" opens the website on the same result, after you confirm linking the browser to the extension's session.

Build and load it:

```bash
npm run build -w extension
```

Then open `chrome://extensions` (or `edge://extensions`), turn on Developer mode, choose Load unpacked, and select `extension/.output/chrome-mv3`.

Settings are build-time environment variables: `WXT_API_BASE_URL` (default `http://localhost:8000`) and `WXT_SITE_BASE_URL` (default `http://localhost:3000`). Changing the API origin is a rebuild, because the origin is also written into the extension's host permissions.

The website's landing page offers the extension as a zip. `npm run build -w frontend` creates it first (`npm run package:site -w extension`, which you can also run on its own).

Capture boundary: the extension reads a page only on the buyer's click (the toolbar icon, or the side panel's "Capture this page" button), only that one page, and only on the two marketplaces. It never crawls, never runs in the background, and never navigates by itself. Its permissions are `activeTab`, `scripting`, `storage`, and `sidePanel`. It has no access to the marketplace sites at install: the panel's button asks for it once, in Chrome's own prompt (an optional host permission the buyer can remove at `chrome://extensions`).

Timing: with the API running, `python scripts/time_checks.py --runs 10` submits real checks and prints the server and wall-clock seconds of each, with the median and the maximum. Add `--output docs/evidence/latency.json` to keep them as evidence.

Developer helper: `python scripts/dev_handoff_demo.py` plays the extension's part of the session handoff and prints a website URL that should open the result after the confirmation prompt.

## Verification commands

```bash
pytest -q
python -m compileall -q api scripts
python scripts/secret_scan.py
python scripts/check_prose.py
pip-audit .

npm run lint
npm run format:check
npm run typecheck
npm test
npm audit --omit=dev --audit-level=high
npm run build
npm run test:e2e -w extension
```

Last full run (2026-11-02): the Python suite passed with 189 tests, ruff, strict mypy, the secret scan and the prose punctuation check were clean, and the JavaScript checks passed (shared 79 tests, extension 357 tests with 2 real-page fixture files skipped until recorded pages are added, frontend 37 tests, lint, the Prettier format check, typecheck, `npm audit --omit=dev` with 0 vulnerabilities in the shipped dependencies on Next.js 16.4.3, the production build, and 6 browser end-to-end tests). The same day the built extension, the trained models and the production website were run together on six real listings from the validation split: see [the real-use check](docs/evidence/2026-11-02-real-use-check.md). `pip-audit` was last run on 2026-10-10. The manual checks that need live marketplace pages and a real browser are listed in `docs/superpowers/audits/2026-10-manual-checks.md`.

## What the buyer sees

The interface is described in `.impeccable.md` and `docs/spec/04_Design_Brief_UI_UX.md`; the places where it differs from the specification are in `docs/CHANGES_FROM_SPEC.md`. Two choices matter when reading the code. The three checks are called Photos, Wording and Seller and price on screen (the report calls them visual, textual and behavioural); the names are in `shared/src/copy.ts`. Buyer-facing text never names a model, a bundle or a timing: the API still sends them, and `SHOW_MODEL_DETAILS` in `shared/src/copy.ts` (off) shows them again.

## Data storage

Sessions, assessments and feedback are kept in one SQLite file, `data/guardianlens.sqlite3` (git-ignored). Set `GUARDIANLENS_DATABASE_PATH` to put it elsewhere. The buyer's own wording and the photo bytes are never written to it. A check that was still running when the server stopped is closed as failed on the next start. There is no admin page: read the file with any SQLite tool (for example `sqlite3 data/guardianlens.sqlite3 "select source, count(*) from assessments group by source"`).

## Replacing development stubs with real models

The final active model bundle must contain:

- CLIP consistency thresholds and an SSCD reference-corpus index.
- A TF-IDF (word and character) plus text-cues logistic regression text model. It replaces the XLM-RoBERTa fine-tune planned in the original specification; see [trained model setup](docs/TRAINED_MODELS.md).
- An XGBoost behavioural model and training-only category price baselines.
- Five-fold out-of-fold component probabilities used to train the late-fusion model.
- A sigmoid calibrator.
- Validation-derived Low, Moderate, and High boundaries.
- Reviewed SHAP explanation templates.
- Dataset split hash, seeds, dependency lock hash, component versions, and artefact SHA-256 values.

The API must refuse to render a real band when an active bundle lacks confirmed boundaries. The stub's placeholder boundaries (`STUB_LOW_MAX` and `STUB_MODERATE_MAX` in `api/services/orchestrator.py`) exist only to exercise the interface.
