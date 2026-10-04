# Response to the 2026-10-01 read-only audit

Source: `audit/GUARDIANLENS_READ_ONLY_AUDIT_2026-10-01.md`. Every factual claim that was spot-checked reproduced exactly
(pHash counts, image-count tail, platform/capture-date facts, group sizes, per-platform AUCs, raw vs calibrated T spread, hashes).
Severities below are this project's own assessment after measuring the effect.

| # | Audit finding | Status | What changed |
|---|---|---|---|
| 1 | `phash_reuse` built from the whole image corpus | **Fixed** | Removed. Image measurements now use only the listing's own first 3 photos (`features.image_metadata`). No cross-listing statistic remains. Measured effect before: at most 13 validation listings. |
| 2 | Offline duplicate/reuse flags and redaction count come from whole-dataset processing and were visible to annotators | **Fixed for the exploratory model** | `references.exploratory_tabular.variant: parity` excludes `reused_image_indicator`, `duplicate_status`, `redacted_pii_count`, `condition` and the capture-time `image_count`. The methodology signals B, V and T never used them. |
| 3 | Image count / selection artifact (11-12 captured images are 95% risky, all Carousell, one capture day) | **Mitigated, not removable** | The count is capped at 3 (what the app accepts). Measured: dropping the 11 listings with 11+ images lowers `tabular_ext` 0.805 -> 0.783 and v2 fusion 0.791 -> 0.767, so most of the gain remains. The v3 notebook reports this sensitivity and the no-metadata ablation. Capture provenance of the original gallery cannot be reconstructed here. |
| 4 | Platform / capture-day / missingness confound | **Documented** | Per-platform and per-language AUC are in every report. Only a new collection batch can test robustness. |
| 5 | Image metadata joined by listing ID: blank for brand-new listings | **Fixed** | `features.image_meta_for` measures unseen listings from their image files (`image_meta_from_files`). Test: `test_image_meta_is_measured_from_files_for_new_listings`. |
| 6 | Hyperparameter tuning not nested inside the outer folds | **Fixed** | `cv.nested_tuning: true`: hyperparameters are re-selected inside every outer training partition (`models.out_of_fold`). |
| 7 | V's SSCD references in out-of-fold include other held-out folds | **Fixed** | `fold_context` rebuilds the V features for each fold with the reference corpus = that fold's training rows only. |
| 8 | Ordinary reporting reads test labels; README said "never reads test" | **Fixed** | `data.load_unlabelled` reads the test split without labels. `verify`, the overview chart and training never see test labels. Only `gl final` reads them. Row counts are now also checked against the manifest. Earlier reports (v1, v2) did show pooled test class balance and platform/category risk rates; disclose that in the thesis. |
| 9 | "T collapsed" warning referred to the calibrated single-signal configuration | **Fixed** | Calibrated single-signal configs are labelled `config X (calibrated alone)` and the warning says a constant calibrated output is not proof the raw signal collapsed. |
| 10 | Resume and provenance checks too weak | **Partly fixed** | Each signal and XLM-R fold stores a fingerprint of its config, split hashes and modelling code; a stale artifact is refused (`--force` to retrain). NPZs now carry listing IDs and fold IDs. Model checkpoints are still not exported (size). |

## Not fixed (out of scope here)
* The historical `group_id` / target builder (`guardianlens_lab`) is no longer in the workspace; exact provenance is only partly recoverable.
* Group disjointness does not prove seller disjointness; there is no seller key.
* Annotation label noise (kappa 0.50 on the QA sample) still caps what any model can reach.
* The app (`GuardianLens_codebase`) still needs an adapter that supplies the same fields (and the same image encoding) as training.
* v1 and v2 results were produced before these fixes and are kept only as reference numbers; v3 is the run to report.
