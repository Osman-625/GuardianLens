"""Regenerates notebooks/GuardianLens_Colab_v2.ipynb (methodology v2: image metadata in V, text-cue T)."""
import json
from pathlib import Path


def md(s):
    return {"cell_type": "markdown", "metadata": {}, "source": s.strip("\n").splitlines(True)}


def code(s):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n").splitlines(True)}


cells = [
md("""
# GuardianLens: Methodology v2 on Google Colab

Methodology v1 (XLM-R + CLIP/SSCD + XGBoost) finished below the pre-agreed bar: fusion ROC AUC **0.658** (needed 0.70).
Two evidence-based changes are tested here, nothing else:

| Change | Why (from the v1 results) |
|---|---|
| **V now also uses image count / resolution / file size** (`--visual-metadata`) | image count was V's strongest input; the same features drove the 0.81 reference model |
| **T = TF-IDF + hand-crafted text cues** instead of XLM-R (`--text-cues`) | XLM-R finished at AUC 0.530 with fusion weight 0.04; text cues (contact, payment, urgency wording) were a top feature elsewhere |

B (behavioural XGBoost), the fusion, calibration, bands and the sealed test are unchanged. v1 stays as the reported methodology
result; this run is reported next to it as "v2 (extended)".

**Before you start**
1. A GPU is not required (nothing is fine-tuned). If the embedding cache on Drive is missing, a T4 makes the CLIP/SSCD step quick.
2. Keep both zips on your Drive: `GuardianLens_Colab_Package.zip` (already there) and the new small `GuardianLens_v2_update.zip`
   (put it in the same folder). The update overlays the new code, so the 209 MB package is not uploaded again.
3. Run the cells top to bottom. The whole run takes about 6-10 minutes.
"""),
md("## 1. Setup"),
code("""
import subprocess
print(subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True).stdout or 'no GPU attached (fine for this run)')
from google.colab import drive
drive.mount('/content/drive')
"""),
code("""
import glob, os

def find(name):
    for base in ('/content/drive/MyDrive/GuardianLens_Training', '/content/drive/MyDrive'):
        p = f'{base}/{name}'
        if os.path.exists(p):
            return p
    hits = glob.glob(f'/content/drive/MyDrive/**/{name}', recursive=True)
    return hits[0] if hits else None

PKG = find('GuardianLens_Colab_Package.zip')
UPD = find('GuardianLens_v2_update.zip')
print('package :', PKG)
print('update  :', UPD)
assert PKG, 'GuardianLens_Colab_Package.zip not found on Drive'
assert UPD, 'GuardianLens_v2_update.zip not found on Drive: upload it next to the package'
"""),
code("""
!rm -rf /content/GuardianLens_Colab
!unzip -q -o "{PKG}" -d /content
!unzip -q -o "{UPD}" -d /content
%cd /content/GuardianLens_Colab
# durable storage: runs and the embedding cache live on Drive (same folders as the v1 run, so v1 can be compared)
!mkdir -p /content/drive/MyDrive/GuardianLens_runs/_evaluations /content/drive/MyDrive/GuardianLens_cache
!rm -rf runs data/cache evaluations
!ln -s /content/drive/MyDrive/GuardianLens_runs runs
!ln -s /content/drive/MyDrive/GuardianLens_cache data/cache
!ln -s /content/drive/MyDrive/GuardianLens_runs/_evaluations evaluations
!pip -q install -r requirements.txt
!grep -n "impl:" config.yaml
!ls runs
"""),
code("!python -m gl check"),
md("`check` must end with `\"ok\": true`. The `ls runs` above should list your v1 run (`..._colab`) so the comparison below works."),
md("""
## 2. Train methodology v2
Signals: **B** (unchanged), **V** (+ image metadata), **T** (text cues), the two references, then the seven-configuration fusion,
calibration, bands, SHAP and charts.
"""),
code("!python -m gl all --visual-metadata --text-cues --tag colab_v2"),
md("## 3. Results against the bar"),
code("""
import json, glob, os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import Image, display, HTML

RUN = 'runs/' + open('runs/LATEST').read().strip()
v1_runs = sorted(r for r in glob.glob('runs/*_colab') if os.path.isdir(r))
RUN1 = v1_runs[-1] if v1_runs else None
print('v2 run:', RUN)
print('v1 run:', RUN1)
m2 = json.load(open(f'{RUN}/validation_metrics.json'))
m1 = json.load(open(f'{RUN1}/validation_metrics.json')) if RUN1 else None

NAMES = {'V': 'V Visual', 'T': 'T Textual', 'B': 'B Behavioural', 'text_baseline': 'Text baseline (TF-IDF)',
         'tabular_ext': 'Exploratory extended tabular', 'fusion': 'FUSION'}
rows = []
for k, m in m2['models'].items():
    op = m['operating']['max_f1']
    rows.append({'model': NAMES.get(k, k.replace('cfg_', 'config ')), 'ROC AUC': round(m['roc_auc']['point'], 3),
                 '95% CI': f"{m['roc_auc']['lo']:.3f}-{m['roc_auc']['hi']:.3f}", 'PR AUC': round(m['pr_auc']['point'], 3),
                 'F1': round(op['f1'], 3), 'precision': round(op['precision'], 3), 'recall': round(op['recall'], 3)})
display(pd.DataFrame(rows).set_index('model'))
display(pd.DataFrame(m2['bands']).set_index('band')[['n', 'risky', 'risky_rate']])
"""),
code("""
# The agreed bar (fixed before the v1 run finished)
f = m2['models']['fusion']['roc_auc']
level = 'GOOD' if f['point'] >= 0.75 else 'MINIMUM USEFUL' if f['point'] >= 0.70 else 'BELOW THE BAR'
b = {r['band']: r for r in m2['bands']}
tb = m2['models']['text_baseline']['roc_auc']['point']
print(f"Fusion ROC AUC {f['point']:.3f}  (95% CI {f['lo']:.3f}-{f['hi']:.3f})  ->  {level}")
print(f"  bar: >= 0.70 minimum useful, >= 0.75 good | text baseline {tb:.3f} | v1 fusion "
      f"{m1['models']['fusion']['roc_auc']['point']:.3f}" if m1 else "")
print(f"  Low band risky rate  {b['Low']['risky_rate']:.2f}  (bar: <= 0.15)   n={b['Low']['n']}")
print(f"  High band risky rate {b['High']['risky_rate']:.2f}  (bar: >= 0.60)   n={b['High']['n']}")
print('  risky rate rises Low -> High:', b['Low']['risky_rate'] <= b['Moderate']['risky_rate'] <= b['High']['risky_rate'])
for k, v in m2['fusion_vs_single'].items():
    d = v['roc_auc']
    print(f"  fusion vs {k}: AUC difference {d['point']:+.3f} (95% CI {d['lo']:+.3f} to {d['hi']:+.3f})")
"""),
code("""
# v1 (methodology) vs v2 (extended): ROC AUC with 95% CI, against the bar
keys = ['B', 'V', 'T', 'fusion']
fig, ax = plt.subplots(figsize=(9, 4.8))
w = 0.36
for j, (m, lab, col) in enumerate([(m1, 'v1 methodology (XLM-R T, plain V)', '#666666'), (m2, 'v2 extended (text-cue T, V + image metadata)', '#D55E00')]):
    if m is None:
        continue
    pts = np.array([m['models'][k]['roc_auc']['point'] for k in keys])
    lo = pts - np.array([m['models'][k]['roc_auc']['lo'] for k in keys])
    hi = np.array([m['models'][k]['roc_auc']['hi'] for k in keys]) - pts
    x = np.arange(len(keys)) + (j - 0.5) * w
    ax.bar(x, pts, w, yerr=[lo, hi], capsize=3, color=col, label=lab)
    for xi, p in zip(x, pts):
        ax.text(xi, 0.03, f'{p:.3f}', ha='center', color='white', fontsize=8, fontweight='bold')
for y, t, ls in ((0.5, 'chance', '--'), (0.70, 'minimum useful (0.70)', ':'), (0.75, 'good (0.75)', ':')):
    ax.axhline(y, ls=ls, color='black', lw=1)
    ax.text(len(keys) - 0.45, y + 0.005, t, fontsize=8, ha='right')
ax.axhline(m2['models']['tabular_ext']['roc_auc']['point'], color='#009E73', lw=1.2)
ax.text(-0.45, m2['models']['tabular_ext']['roc_auc']['point'] + 0.005, 'exploratory extended tabular (reference)', fontsize=8, color='#009E73')
ax.set_xticks(range(len(keys)), ['B behavioural', 'V visual', 'T textual', 'FUSION'])
ax.set_ylim(0.4, 0.9)
ax.set_ylabel('Validation ROC AUC')
ax.set_title('Methodology v1 vs v2 (95% CI, validation)', fontweight='bold')
ax.legend(fontsize=8, loc='upper left')
plt.tight_layout()
out = f'{RUN}/figures/methodology_v1_vs_v2.png'
plt.savefig(out, dpi=140)
plt.show()
"""),
md("""
**How to read the numbers**
- v2 passes the bar only if the fusion AUC is **0.70 or more** and the bands are usable (see the band checks above).
- Judge changes by the confidence intervals, not the point estimates: with 86 risky validation listings a gain smaller than
  about 0.05 AUC is not provable.
- If V's gain comes from image metadata, check `group_performance` below: it should hold on **both** platforms, otherwise it is
  a platform effect rather than a real signal.
"""),
code("""
ORDER = ['dataset_overview', 'config_comparison', 'model_comparison', 'roc', 'precision_recall', 'score_distributions',
         'calibration_compare', 'band_chart', 'threshold_sweep_fusion', 'confusion_flag_moderate_or_high',
         'confusion_flag_high_only', 'group_performance', 'stacker_weights', 'shap_summary', 'visual_feature_dists']
for name in ORDER:
    f = f'{RUN}/figures/{name}.png'
    if os.path.exists(f):
        display(HTML(f'<h4 style="margin:18px 0 4px">{name.replace("_", " ")}</h4>'))
        display(Image(filename=f))
"""),
code("""
diag = json.load(open(f'{RUN}/train_diagnostics.json'))
print('Text-cue effects in T (standardised coefficients):')
for k, v in list(diag['T']['cue_effects'].items())[:8]:
    print(f'  {k:16s} {v:+.3f}')
print('\\nV head coefficients:')
for k, v in diag['V']['coefficients'].items():
    print(f'  {k:28s} {v:+.3f}')
print()
print(open(f'{RUN}/explanations_sample.md', encoding='utf-8').read()[:2500])
"""),
md("""
## 4. Final test: run once, only after you have chosen the final model
The test split is sealed and has not been used by v1 or v2. `final` scores it with the frozen models, fusion, calibrator and
bands. A second run on the same model is refused. Remove the `#` to run it.
"""),
code("# !python -m gl final"),
md("## 5. Save and download\nEverything is already on Drive in `MyDrive/GuardianLens_runs/`. This also downloads the report and charts."),
code("""
import shutil
tmp = '/content/run_results_v2'
shutil.rmtree(tmp, ignore_errors=True)
shutil.copytree(RUN, tmp, ignore=shutil.ignore_patterns('xlmr', 'models', '*.joblib'))
shutil.make_archive('/content/run_results_v2', 'zip', tmp)
from google.colab import files
files.download('/content/run_results_v2.zip')
"""),
]
nb = {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"provenance": []},
      "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 5}
out = Path(__file__).resolve().parent.parent / "notebooks" / "GuardianLens_Colab_v2.ipynb"
out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print("wrote", out)
