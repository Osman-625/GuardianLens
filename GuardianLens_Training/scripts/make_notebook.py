"""Regenerates notebooks/GuardianLens_Colab.ipynb"""
import json
from pathlib import Path


def md(s):
    return {"cell_type": "markdown", "metadata": {}, "source": s.strip("\n").splitlines(True)}


def code(s):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n").splitlines(True)}


cells = [
md("""
# GuardianLens: training on Google Colab (GPU)

Implements the methodology: three signals, out-of-fold fusion, calibration, risk bands.

| Signal | Model |
|---|---|
| **T** Textual | XLM-RoBERTa fine-tune, 5 group-safe folds, class weights, early stopping |
| **V** Visual | CLIP photo-title consistency + SSCD copy detection against a train-only reference corpus |
| **B** Behavioural | XGBoost on price, category price ratio, seller fields and missingness flags (+ TreeSHAP) |
| **Fusion** | logistic regression on out-of-fold scores + availability flags, sigmoid calibration, Low/Moderate/High bands |

It also reports the seven configurations (V, T, B, V+T, V+B, T+B, V+T+B), a TF-IDF text baseline, and an exploratory
"everything in one" tabular model, all with confidence intervals and charts.

**Before you start**
1. Runtime -> Change runtime type -> **T4 GPU**.
2. Upload `GuardianLens_Colab_Package.zip` to the top level of your Google Drive (`MyDrive`).
3. Run the cells top to bottom. Runs and caches are stored **on Drive**, so if Colab disconnects you can re-run
   cells 1-3 and the training cell: finished signals and finished XLM-R folds are skipped.

The sealed **test** split is only touched by the final cell, which you run yourself.
"""),
md("## 1. Setup"),
code("""
import subprocess
print(subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True).stdout or 'NO GPU: switch the runtime to T4 GPU')
from google.colab import drive
drive.mount('/content/drive')
"""),
code("""
%%bash
set -e
rm -rf /content/GuardianLens_Colab
unzip -q -o /content/drive/MyDrive/GuardianLens_Colab_Package.zip -d /content
cd /content/GuardianLens_Colab
# durable storage: runs (incl. XLM-R fold models) and the embedding cache live on Drive
mkdir -p /content/drive/MyDrive/GuardianLens_runs /content/drive/MyDrive/GuardianLens_cache
rm -rf runs data/cache evaluations
ln -s /content/drive/MyDrive/GuardianLens_runs runs
ln -s /content/drive/MyDrive/GuardianLens_cache data/cache
mkdir -p /content/drive/MyDrive/GuardianLens_runs/_evaluations
ln -s /content/drive/MyDrive/GuardianLens_runs/_evaluations evaluations
pip -q install -r requirements.txt
"""),
code("""
%cd /content/GuardianLens_Colab
!python -m gl check
"""),
md("`check` must end with `\"ok\": true`: no listing group crosses the splits and the split files are unmodified."),
md("""
## 2. Train: B, V, T, references, fusion, calibration, bands
First run: roughly 25-45 minutes on a T4 (CLIP+SSCD embeddings, the five XLM-R folds, then the quick signals).
To resume an interrupted run, replace `--tag colab` with `--run <run folder name>`.
"""),
code("!python -m gl all --xlmr --tag colab"),
md("## 3. Results"),
code("""
import json, os
import pandas as pd
from IPython.display import Image, display, HTML

RUN = 'runs/' + open('runs/LATEST').read().strip()
print('run folder:', RUN)
val = json.load(open(f'{RUN}/validation_metrics.json'))
NAMES = {'V': 'V Visual', 'T': 'T Textual (XLM-R)', 'B': 'B Behavioural', 'text_baseline': 'Text baseline (TF-IDF)',
         'tabular_ext': 'Exploratory extended tabular', 'fusion': 'FUSION'}
rows = []
for k, m in val['models'].items():
    op = m['operating']['max_f1']
    rows.append({'model': NAMES.get(k, k.replace('cfg_', 'config ')), 'ROC AUC': round(m['roc_auc']['point'], 3),
                 '95% CI': f"{m['roc_auc']['lo']:.3f}-{m['roc_auc']['hi']:.3f}", 'PR AUC': round(m['pr_auc']['point'], 3),
                 'F1': round(op['f1'], 3), 'precision': round(op['precision'], 3), 'recall': round(op['recall'], 3),
                 'score std': round(m['calibration']['score_std'], 3)})
display(pd.DataFrame(rows).set_index('model'))
print(f"chance AUC = 0.5 | base rate = {val['prevalence']:.3f} | F1 of 'flag everything' = {val['baselines']['flag_everything_f1']:.3f}")
display(pd.DataFrame(val['bands']).set_index('band')[['n', 'risky', 'risky_rate']])
"""),
code("""
ORDER = ['dataset_overview', 'config_comparison', 'model_comparison', 'roc', 'precision_recall', 'score_distributions',
         'calibration_compare', 'band_chart', 'threshold_sweep_fusion', 'confusion_flag_moderate_or_high',
         'confusion_flag_high_only', 'group_performance', 'stacker_weights', 'shap_summary', 'visual_feature_dists',
         'xlmr_training_history']
for name in ORDER:
    f = f'{RUN}/figures/{name}.png'
    if os.path.exists(f):
        display(HTML(f'<h4 style="margin:18px 0 4px">{name.replace("_", " ")}</h4>'))
        display(Image(filename=f))
"""),
md("""
**How to read the charts**
- `config_comparison`: the seven V/T/B configurations with 95% CIs. Whiskers touching the dashed line are not distinguishable from chance.
- `model_comparison`: each signal, the two references and the fusion.
- `score_distributions`: blue (legitimate) and orange (risky) should separate. One narrow spike = a collapsed model.
- `xlmr_training_history`: per-fold train loss, early-stopping AUC and score spread. Spread near 0 = collapse (what broke the first two runs).
- `calibration_compare`: reliability before and after the sigmoid; `band_chart`: the risky share should rise from Low to High.
- `shap_summary`: which behavioural features push a listing toward risk. `visual_feature_dists`: the CLIP / SSCD inputs by class.
"""),
code("""
print(open(f'{RUN}/explanations_sample.md', encoding='utf-8').read()[:3500])
"""),
md("""
## 4. Optional extension (not in the methodology)
Adds image count / resolution / file size to V. In exploration these were the strongest single drivers, so this shows how much
they would add. Report it as an extension, not as the methodology result. Remove the `#` to run (reuses the cached embeddings).
"""),
code("# !python -m gl all --visual-metadata --tag colab_vmeta"),
md("""
## 5. Final test: run once, when you are done
The test split is sealed. `final` scores it with the frozen models, fusion, calibrators and bands, writes the `*_test.png`
charts and records the run in the test ledger. A second run on the same model is refused. Remove the `#` to run.
"""),
code("# !python -m gl final"),
code("""
for name in ['config_comparison', 'model_comparison', 'roc', 'precision_recall', 'calibration_compare', 'band_chart',
             'confusion_flag_moderate_or_high', 'group_performance']:
    f = f'{RUN}/figures/{name}_test.png'
    if os.path.exists(f):
        display(Image(filename=f))
"""),
md("## 6. Save and download\nEverything is already on Drive in `MyDrive/GuardianLens_runs/`. This also downloads the report and charts (without the large model files)."),
code("""
import shutil, glob
tmp = '/content/run_results'
shutil.rmtree(tmp, ignore_errors=True)
shutil.copytree(RUN, tmp, ignore=shutil.ignore_patterns('xlmr', 'models', '*.joblib'))
shutil.make_archive('/content/run_results', 'zip', tmp)
from google.colab import files
files.download('/content/run_results.zip')
"""),
md("Open `report.html` in the downloaded zip for the full report (every table and chart on one page)."),
]
nb = {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"provenance": []},
      "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 5}
out = Path(__file__).resolve().parent.parent / "notebooks" / "GuardianLens_Colab.ipynb"
out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print("wrote", out)
