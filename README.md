# GuardianLens FYP2 First Draft

GuardianLens is a multimodal, explainable fraud-risk decision-support prototype for buyers checking Mudah.my and Carousell product listings before payment. This archive turns the supplied pre-implementation documents into a runnable product scaffold while preserving the locked scope and separating development stubs from research evidence.

## Read this first

The current API runs with `GUARDIANLENS_STUB_MODE=true` by default. It executes contract stubs for the visual, textual, behavioural, fusion, and explanation stages so the seven-screen workflow can be developed and tested before trained artefacts exist.

Stub scores are displayed with a permanent warning. They are not CLIP, SSCD, XLM-RoBERTa, XGBoost, calibrated late-fusion, or SHAP results. They must not be used in Chapter 4 metrics, the user study, a real buying decision, or any claim that GuardianLens has been trained.

## Included

- Next.js and TypeScript source for landing, submission, processing, result, explanation, feedback, session history, and research administration.
- FastAPI endpoints matching the proposed `/api/v1` contract.
- Field-level validation, unsupported Chinese-dominant text rejection, image type and size checks, metadata-stripping re-encoding, PII scrubbing, session ownership checks, feedback, history, rate limiting, and structured error envelopes.
- Development-only five-stage pipeline stubs with explicit missing-signal handling.
- Supabase SQL migrations for the product schema, research schema, RLS posture, private storage buckets, and the hold-out study-listing trigger.
- ML interfaces, bundle-manifest schema, explanation-template draft, and a latency harness that marks stub timing invalid for NFR-02.
- Research CSV templates and draft consent, session, and questionnaire materials. No generated labels, participants, or study rows are included.
- Automated backend and ML contract tests, CI source, secret scanning, and prose punctuation checks.
- The original eight specification documents under `docs/spec/`.

## Repository map

```text
guardianlens/
  frontend/             Next.js screens S1 to S7
  api/                  FastAPI application and tests
  ml/                   Contracts, bundle schema, configs, and latency harness
  db/migrations/        Supabase migrations
  research/             Human-only import templates and study drafts
  docs/spec/             Supplied pre-implementation documents
  docs/plans/            Build and next-step records
  docs/ch4-notes/        Incremental implementation notes
  scripts/               Local development and verification helpers
```

## Quick start on Windows

Prerequisites: Python 3.12 or 3.13, Node.js 22, npm, and Git.

```powershell
cd GuardianLens_First_Draft
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
cd frontend
npm install
cd ..
Copy-Item .env.example .env
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

Open:

- Web: `http://localhost:3000`
- API health: `http://localhost:8000/health`
- OpenAPI: `http://localhost:8000/docs`

The first connected `npm install` should create `frontend/package-lock.json`. Review it, run the frontend checks, then commit it before treating GL-P0-02 as complete.

## Quick start on Linux or macOS

```bash
cd GuardianLens_First_Draft
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cd frontend && npm install && cd ..
cp .env.example .env
./scripts/dev.sh
```

## Verification commands

```bash
pytest -q
python -m compileall -q api ml scripts
python scripts/secret_scan.py
python scripts/check_prose.py

cd frontend
npm run lint
npm run typecheck
npm run build
```

At generation time, the Python test suite passed with 9 tests. Python compilation, the secret scan, and the prose punctuation check also passed. Frontend dependency installation and build verification were not executed because the generation sandbox had no DNS access to the npm registry. Run the three frontend commands on a connected machine before claiming the frontend is verified.

## Development admin access

Set a local-only token in `.env`:

```env
GUARDIANLENS_DEV_ADMIN_TOKEN=replace-with-a-random-local-token
```

Open `/admin` and enter the same value. This is an explicit temporary gate. It does not satisfy the final Supabase Auth and role-check requirement and must be replaced before production-like testing.

## Supabase setup

Do not disable stub mode yet. First:

1. Confirm proposal P-2 with the supervisor.
2. Create a Supabase project and record the current free-tier limits.
3. Apply migrations in filename order with the Supabase CLI.
4. Verify every table, policy, trigger, and private bucket in a disposable project.
5. Implement `api/repositories/supabase.py` with server-side service-role access and explicit session ownership checks.
6. Add Supabase Auth verification for all `/api/v1/admin/*` endpoints.
7. Add integration tests against a fresh migrated project.
8. Only then set `GUARDIANLENS_STUB_MODE=false`.

The service-role key must remain server-side. Never place it in `NEXT_PUBLIC_*`, browser code, logs, screenshots, or committed files.

## Replacing development stubs with real models

The final active model bundle must contain:

- CLIP consistency thresholds and an SSCD reference-corpus index.
- A fine-tuned XLM-RoBERTa checkpoint.
- An XGBoost behavioural model and training-only category price baselines.
- Five-fold out-of-fold component probabilities used to train the late-fusion model.
- A sigmoid calibrator.
- Validation-derived Low, Moderate, and High boundaries.
- Reviewed SHAP explanation templates.
- Dataset split hash, seeds, dependency lock hash, component versions, and artefact SHA-256 values.

The API must refuse to render a real band when an active bundle lacks confirmed boundaries. The development boundaries in `ml/configs/dev_stub.yaml` exist only to exercise the interface.

## Open items that still block later gates

- O-1: second annotator.
- O-2: official FYP2 dates.
- O-3: INTI ethics or approval requirement.
- O-4: approved retention period.
- O-5: licences for the exact pretrained weights.
- O-6: current Supabase free-tier limits.
- O-7: validation-derived risk-band boundaries.
- O-8: written record of supervisor sign-off on Chapter 3 sections 3.3.7 to 3.3.9.

See `FIRST_DRAFT_STATUS.md` and `docs/plans/phase-0-first-draft.md` for the exact completion boundary.
