# GuardianLens training workspace (v2)

Implements the project methodology end to end: three signals (Visual, Textual, Behavioural) -> out-of-fold fusion ->
sigmoid calibration -> Low / Moderate / High bands -> seven-configuration ablation -> sealed test, with charts.

| Signal | Model | Code |
| --- | --- | --- |
| **T** Textual | TF-IDF word/character features + text cues, logistic regression, group-safe nested tuning | `gl/models.py` (`TextCueSignal`) |
| **V** Visual | CLIP photo-title consistency + SSCD copy detection vs a train-only reference corpus, logistic head | `gl/visual.py`, `gl/models.py` |
| **B** Behavioural | XGBoost on price, category price ratio, seller fields + missingness flags; TreeSHAP | `gl/models.py`, `gl/features.py` |
| **Fusion** | logistic regression on out-of-fold scores + availability flags, sigmoid calibration, bands | `gl/fusion.py` |
| References | TF-IDF text baseline (methodology step 2); exploratory "everything in one" tabular model | `gl/models.py` |

The latest selected run is `runs/final_test_results/20261002_062026_colab_v3_noMeta`. Its copied reports do not include fitted joblib artifacts. Deployment instructions are in `../GuardianLens_codebase/docs/TRAINED_MODELS.md`. Historical XLM-R runs are retained for comparison.

## Train on Google Colab (main route)

1. Package: `dist/GuardianLens_Colab_Package.zip` (rebuild with `python scripts/make_colab_package.py`).
2. Upload it to the top of Google Drive. Open `notebooks/GuardianLens_Colab.ipynb` in Colab, runtime **T4 GPU**, run top to bottom.
3. It runs `python -m gl all --text-cues --tag colab` and shows every chart inline. Runs and the embedding cache live on Drive, so a
   dropped session resumes (finished signals are skipped).

To let Claude Code drive the Colab session, see [`docs/COLAB_MCP.md`](docs/COLAB_MCP.md).

## Commands (`python -m gl ...`)

| Command | What it does |
| --- | --- |
| `check` | Verifies split hashes, no group crosses splits, class counts, images exist (`--freeze` rewrites the manifest) |
| `all --text-cues [--tag T] [--run ID]` | New run (or resume `--run`): signals B, V, references, TF-IDF/text-cues T, then fusion, calibration, bands, validation report. Never reads test labels (the test split is read without labels for integrity checks) |
| `signal B\|V\|T\|text_baseline\|tabular_ext` | Train one signal into a run |
| `fuse` | Out-of-fold fusion of the trained signals, seven configurations, calibration, bands, SHAP, report |
| `evaluate` | Rebuild validation metrics, charts and report |
| `final` | Score the sealed test split **once** (frozen models/thresholds/bands); recorded in `evaluations/test_ledger.json` |
| `predict --input in.csv --output out.csv` | Score new listings (missing signals handled by availability flags) |

`all --visual-metadata` adds image measurements (first 3 photos: count, sizes, file size) to V. That is **not** in the methodology; use it only as a labelled extension.

## Charts (`runs/<run>/figures/`, all embedded in `report.html`)

`dataset_overview`, `config_comparison` (7 configurations, 95% CIs), `model_comparison`, `roc`, `precision_recall`,
`score_distributions`, `calibration_compare` (before/after sigmoid), `band_chart`, `threshold_sweep_fusion`,
`confusion_flag_*`, `group_performance`, `stacker_weights`, `shap_summary`, `visual_feature_dists`, `xlmr_training_history`;
`*_test.png` after `gl final`. Also `explanations_sample.md` (SHAP/CLIP/SSCD -> buyer-facing sentences).

## Audit response

See [`docs/AUDIT_RESPONSE.md`](docs/AUDIT_RESPONSE.md) for how the 2026-10-01 read-only audit findings were handled.

## Protocol

* `data/splits/*.csv`: the frozen v1 split (1,537 / 330 / 330), grouped by `group_id`; hashes checked on every run.
* Everything is fitted on train (grouped 5-fold, hyperparameters re-selected inside each fold) or chosen on validation. The calibrator uses out-of-fold train scores only.
  The SSCD reference corpus is the train images (same-group photos excluded). XLM-R early stopping uses an inner slice of each fold.
* Labels are AI-annotated *risk* (suspicious + scam_fraud = 1), not confirmed fraud.
* `models/*.joblib` bundles are pickles: only load ones you created.

## Run locally (CPU, quick check only)

```powershell
.\setup.ps1
$py = "$env:USERPROFILE\venvs\guardianlens\Scripts\python.exe"
& $py -m gl all --no-visual      # B + references + fusion; V needs images and CLIP/SSCD assets; add --text-cues for CPU text training
& $py -m pytest tests -q
```

## Layout

```
config.yaml   gl/ (code)   data/splits/   runs/   evaluations/   notebooks/   scripts/   docs/COLAB_MCP.md   docs/history/   tests/
```
