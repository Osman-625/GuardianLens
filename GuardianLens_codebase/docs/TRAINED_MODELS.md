# Connect the latest trained run

Selected run: `20261002_062026_colab_v3_noMeta`, created 2 October 2026.

The run's T signal is **TF-IDF word and character features + text cues + logistic regression** (`TextCueSignal`), not XLM-RoBERTa. The separate `text_baseline` is a comparison model, not the T model used by fusion. B is XGBoost. V uses CLIP + SSCD reference similarity with a logistic head and excludes image metadata. Fusion uses the saved logistic stacker and sigmoid calibrator.

The fitted artifacts downloaded from Google Drive are in:

`../GuardianLens_Training/Drive_Artifacts_2026-10-06/runs/20261002_062026_colab_v3_noMeta`

This folder contains the required files from the same run:

- `models/T.joblib`
- `models/B.joblib`
- `models/V.joblib`
- `fusion.joblib`
- `run.json`

It also contains `train_diagnostics.json`, predictions and evaluation reports. The earlier `runs/final_test_results/...` copy contains reports without the fitted models; use the downloaded run path above for inference. Keep the downloaded artifacts and their metadata together.

Do not substitute `text_baseline.joblib` for `T.joblib`. Do not reconstruct fusion from the report weights: the report omits fitted intercepts and calibration parameters. This integration never retrains a model or reads test labels.

## CPU setup

From `GuardianLens_codebase`, the serving dependencies come with the conda environment `Guardianlens_venv` (Python 3.13, the CPU build of PyTorch, scikit-learn, XGBoost, and the test tools); a GPU is not required. Create it once in an Anaconda terminal:

```powershell
conda env create -f environment.yml
conda activate Guardianlens_venv
python -m pip check
```

To change a pin later, edit `pyproject.toml` and run `conda env update -f environment.yml --prune`.

The `trained` extra pins NumPy, pandas, scikit-learn and XGBoost to the selected run's recorded versions. The existing sibling `GuardianLens_Training/gl` modules provide the classes referenced by the saved artifacts; the model, fusion, feature and visual modules have been checked against the v3 source package.

Set these values in `.env`:

```dotenv
GUARDIANLENS_INFERENCE_MODE=trained
GUARDIANLENS_MODEL_RUN_DIR="../GuardianLens_Training/Drive_Artifacts_2026-10-06/runs/20261002_062026_colab_v3_noMeta"
```

`GUARDIANLENS_INFERENCE_MODE=trained` selects the saved models. Restart the API from `GuardianLens_codebase` after changing the environment. Trained mode fails at startup if required fitted artifacts are missing and never silently falls back to development scores.

## Visual assets

The downloaded reference cache and SSCD checkpoint have been copied into the training workspace at these paths and checked against their downloaded hashes:

- `data/cache/visual__openai_clip_vit_base_patch32.npz`
- `data/cache/sscd/sscd_disc_mixup.torchscript.pt`

These paths are relative to `GuardianLens_Training`, not `GuardianLens_codebase`. The approved `data/splits/train.csv` has also been verified against the run's recorded SHA-256.

The `openai/clip-vit-base-patch32` model and processor are separate dependencies; both have been found in the local Hugging Face cache. The API must use that same cache when started. Serving loads these assets with `local_files_only=True`, so it does not download missing assets during an assessment. Finding the files does not establish successful model loading; verify runtime readiness below.

The adapter uses only the approved training references and keeps new upload embeddings in memory. Missing visual assets produce an unavailable V signal; trained fusion receives NaN/availability=0. Health reports the missing visual asset reason.

## Verify

After installing dependencies and restarting the API:

1. Check `GET /health`: inference must be trained, the active bundle must be `20261002_062026_colab_v3_noMeta`, required artifacts must be present, and visual readiness must be true for all three signals to work.
2. Submit a new assessment with a valid listing photo and text. Confirm `development_stub=false`, the selected `model_bundle_label`, and available textual, behavioural and visual signal cards with probabilities.
3. Confirm the website displays that new trained result. `GET /health` names the active bundle.

Assessments use the saved probability boundaries (approximately 16.3244% and 46.6517%). Bands are assigned using the unrounded probability.

For the serving contract tests (the `dev` tools are already in the conda environment), run:

```powershell
python -m pytest api/tests/test_trained_models.py api/tests/test_api.py -q -p no:cacheprovider
```

Check for skipped tests. These tests use disposable fitted models and mock visual loading; they do not replace the real-bundle assessment check above.

The website and extension display API-provided descriptions, so this change does not require an extension rebuild. Old assessment results remain historical snapshots; submit a new check after restarting the API.

## Status on this machine (2026-10-06)

The fitted files from the Drive download (`GuardianLens_Training/Drive_Artifacts_2026-10-06`) are installed in the run folder that `.env` points at, and `.env` has `GUARDIANLENS_INFERENCE_MODE=trained`. A check through the API reported the bundle `20261002_062026_colab_v3_noMeta`, `development_stub: false`, and all three signals available (visual, textual, behavioural). `torch` and `transformers` are installed for the visual signal.

- **`B.joblib` was rebuilt.** The Colab-saved file could not be restored by XGBoost 3.4.1 here ("input stream corrupted"), although the same version wrote it. The Model part inside the pickle loads on its own (150 trees, 10 features), so the same `BehaviouralSignal` was re-saved with that booster. Its predictions on the 330 validation rows equal `signals/B.npz` exactly (maximum difference 0.0). The original is kept as `models/B.colab_original.bak` and the details are in `models/README_B_REPAIR.md`. No model was retrained.
- **Start-up takes about 25 seconds.** It used to take about 9 minutes, because the training workspace's cache loader (`gl.visual._load_cache`) re-decompresses the whole compressed `.npz` for every listing. The API now reads the file once with `load_reference_cache` in `api/services/trained_visual.py`; `api/tests/test_visual_cache.py` pins the result and the speed. Wait for `GET /health` to report the bundle before submitting a check. Checks took 1.6 to 2.2 seconds with 2, 5, and 10 photos (the first check after start-up took 5.8 seconds while the models warmed up), inside the 10 second budget (NFR-02).
- **The API tests do not load the models.** `api/tests/conftest.py` forces stub inference for every test, whatever `.env` says, so the suite stays fast.

## What buyers see of the models

Buyer-facing text names no model. The API result still carries `model_bundle_label`, `total_latency_ms` and each signal's `summary` (for example "Analysed using ..."), and the researcher can read them from `/api/v1/assess/{id}/result`. The website and the panel hide them: `SHOW_MODEL_DETAILS` in `shared/src/copy.ts` is `false`, and the explanation page keeps the hidden elements in the page. Reasons and scope notes are written in plain words (for example "The seller rating (4.8) raised the risk estimate"). On 2026-11-02 the trained bundle `20261002_062026_colab_v3_noMeta` answered six real validation-split listings in 2.6 to 4.8 seconds each through the website and the extension panel; see `docs/evidence/2026-11-02-real-use-check.md`.
