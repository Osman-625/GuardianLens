# Phase 0 First-Draft Build Record

## Scope completed in this archive

- Repository structure for `frontend/`, `api/`, `ml/`, `db/migrations/`, `research/`, and `docs/`.
- FastAPI request contract, session ownership checks, structured errors, image validation and re-encoding, PII scrub, feedback, history, development admin boundary, and tests.
- Seven-screen Next.js source draft with responsive CSS and the required decision-support wording.
- Supabase product, research, RLS, and storage migrations from document 05.
- ML component contracts, bundle manifest schema, explanation-template draft, and latency-harness boundary.
- Research import templates and draft study materials without generated participant or label data.

## Explicitly incomplete

- Real CLIP, SSCD, XLM-RoBERTa, XGBoost, late-fusion, calibration, and SHAP artefacts.
- Supabase repository adapter and Supabase Auth admin integration.
- Confirmed risk-band boundaries, retention period, ethics workflow, official dates, second annotator, and model-weight licences.
- Frontend lockfile and build verification. The generation sandbox could not resolve the npm registry. `package.json` contains exact direct dependency pins, but `npm install` must be run on a connected machine to create and commit `package-lock.json`.
- Real NFR-02 latency evidence. The included harness marks stub runs invalid.

## Next code-level task

Wire `api/repositories/supabase.py` after P-2 and the Supabase project are confirmed. Write contract tests against a disposable migrated project before disabling `GUARDIANLENS_STUB_MODE`.
