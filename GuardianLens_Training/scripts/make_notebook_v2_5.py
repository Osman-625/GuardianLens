"""Regenerates notebooks/GuardianLens_Colab_v2_5.ipynb (ablation attribution + guarded sealed test for the v2 run)."""
import json
from pathlib import Path


def md(s):
    return {"cell_type": "markdown", "metadata": {}, "source": s.strip("\n").splitlines(True)}


def code(s):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n").splitlines(True)}


cells = [
md("""
# GuardianLens: Methodology v2.5 on Google Colab

v2 (text-cue T + image metadata in V) reached fusion ROC AUC **0.791** on validation, past the agreed bar. v2.5 does the last two steps:

1. **Ablation (about 3 minutes):** re-run v2 *without* image metadata, so the gain can be attributed. Three runs are compared:
   `v1` (XLM-R T, plain V) -> `v2 no-meta` (text-cue T, plain V) -> `v2` (text-cue T, V + image metadata).
2. **Final sealed test (once):** score the held-out test split with the frozen v2 models, fusion, calibrator and bands.
   It is behind a typed confirmation so "Run all" cannot trigger it by accident.

No model code changed since v2, so the same two Drive files are used: `GuardianLens_Colab_Package.zip` and `GuardianLens_v2_update.zip`.
The v2 and v1 runs must still be in `MyDrive/GuardianLens_runs/`.
"""),
md("## 1. Setup"),
code("""
import subprocess
print(subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True).stdout or 'no GPU attached (fine; a T4 only speeds up the test-image embedding)')
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
assert PKG and UPD, 'package or v2 update zip not found on Drive'
"""),
code("""
!rm -rf /content/GuardianLens_Colab
!unzip -q -o "{PKG}" -d /content
!unzip -q -o "{UPD}" -d /content
%cd /content/GuardianLens_Colab
!mkdir -p /content/drive/MyDrive/GuardianLens_runs/_evaluations /content/drive/MyDrive/GuardianLens_cache
!rm -rf runs data/cache evaluations
!ln -s /content/drive/MyDrive/GuardianLens_runs runs
!ln -s /content/drive/MyDrive/GuardianLens_cache data/cache
!ln -s /content/drive/MyDrive/GuardianLens_runs/_evaluations evaluations
!pip -q install -r requirements.txt
!python -m gl check | tail -4
"""),
code("""
import json, glob, os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import Image, display, HTML
from sklearn.metrics import roc_auc_score, roc_curve

def runs_with(suffix):
    return sorted(r for r in glob.glob('runs/*') if os.path.isdir(r) and r.endswith(suffix))

V1 = runs_with('_colab')
V2 = runs_with('_colab_v2')
print('v1 runs      :', V1)
print('v2 runs      :', V2)
assert V1 and V2, 'v1 and v2 runs must exist in MyDrive/GuardianLens_runs'
V1_RUN, V2_RUN = V1[-1], V2[-1]
assert os.path.exists(f'{V2_RUN}/fusion.joblib'), 'the v2 run has no saved models'
print('using v1 =', V1_RUN, '| v2 =', V2_RUN)
"""),
md("## 2. Ablation: v2 without image metadata\nReuses the cached embeddings. Skips itself if it already ran."),
code("""
NOMETA = runs_with('_colab_v2_noMeta')
if NOMETA:
    print('ablation run already exists, skipping:', NOMETA[-1])
else:
    get_ipython().system('python -m gl all --text-cues --tag colab_v2_noMeta')
NOMETA = runs_with('_colab_v2_noMeta')
NM_RUN = NOMETA[-1]
print('v2 no-meta run:', NM_RUN)
"""),
md("## 3. Where does the gain come from?"),
code("""
M = {name: json.load(open(f'{r}/validation_metrics.json')) for name, r in
     [('v1: XLM-R T, plain V', V1_RUN), ('v2 no-meta: text-cue T, plain V', NM_RUN), ('v2: text-cue T + V image metadata', V2_RUN)]}
keys = ['B', 'V', 'T', 'fusion']
rows = []
for name, m in M.items():
    r = {'run': name}
    for k in keys:
        a = m['models'][k]['roc_auc']
        r[k] = f"{a['point']:.3f} [{a['lo']:.3f}, {a['hi']:.3f}]"
    rows.append(r)
display(pd.DataFrame(rows).set_index('run'))

def paired_auc_diff(run_a, run_b, n=1000, seed=42):
    A = pd.read_csv(f'{run_a}/val_predictions.csv')[['listing_id', 'target', 'group_id', 'p_fusion']]
    B = pd.read_csv(f'{run_b}/val_predictions.csv')[['listing_id', 'p_fusion']]
    d = A.merge(B, on='listing_id', suffixes=('_a', '_b'))
    y, a, b, g = d.target.values, d.p_fusion_a.values, d.p_fusion_b.values, d.group_id.values
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(g, return_inverse=True)
    members = [np.flatnonzero(inv == i) for i in range(len(uniq))]
    vals = []
    for _ in range(n):
        idx = np.concatenate([members[i] for i in rng.integers(0, len(uniq), len(uniq))])
        if len(set(y[idx])) < 2:
            continue
        vals.append(roc_auc_score(y[idx], a[idx]) - roc_auc_score(y[idx], b[idx]))
    return roc_auc_score(y, a) - roc_auc_score(y, b), np.percentile(vals, 2.5), np.percentile(vals, 97.5)

print('Paired fusion AUC differences (same validation listings, 95% CI over listing groups):')
for lab, a_, b_ in [('effect of text-cue T  (v2 no-meta minus v1)', NM_RUN, V1_RUN),
                    ('effect of V image metadata (v2 minus v2 no-meta)', V2_RUN, NM_RUN),
                    ('both changes (v2 minus v1)', V2_RUN, V1_RUN)]:
    p, lo, hi = paired_auc_diff(a_, b_)
    verdict = 'real' if lo > 0 else 'not distinguishable from zero' if hi >= 0 else 'worse'
    print(f'  {lab:52s} {p:+.3f}  [{lo:+.3f}, {hi:+.3f}]  {verdict}')
"""),
code("""
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
cols = ['#666666', '#E69F00', '#D55E00']
w = 0.26
ax = axes[0]
for j, ((name, m), col) in enumerate(zip(M.items(), cols)):
    pts = np.array([m['models'][k]['roc_auc']['point'] for k in keys])
    lo = pts - np.array([m['models'][k]['roc_auc']['lo'] for k in keys])
    hi = np.array([m['models'][k]['roc_auc']['hi'] for k in keys]) - pts
    x = np.arange(len(keys)) + (j - 1) * w
    ax.bar(x, pts, w, yerr=[lo, hi], capsize=3, color=col, label=name)
    for xi, p in zip(x, pts):
        ax.text(xi, 0.43, f'{p:.2f}', ha='center', color='white', fontsize=8, fontweight='bold')
for y_, t, ls in ((0.5, 'chance', '--'), (0.70, 'minimum useful', ':'), (0.75, 'good', ':')):
    ax.axhline(y_, ls=ls, color='black', lw=1)
    ax.text(3.45, y_ + 0.004, t, fontsize=8, ha='right')
ax.set_xticks(range(len(keys)), ['B behavioural', 'V visual', 'T textual', 'FUSION'])
ax.set_ylim(0.4, 0.9)
ax.set_ylabel('Validation ROC AUC')
ax.set_title('Signals and fusion across the three runs (95% CI)', fontweight='bold')
ax.legend(fontsize=7, loc='upper left')

ax = axes[1]
for (name, _), r, col in zip(M.items(), [V1_RUN, NM_RUN, V2_RUN], cols):
    d = pd.read_csv(f'{r}/val_predictions.csv')
    fpr, tpr, _ = roc_curve(d.target, d.p_fusion)
    ax.plot(fpr, tpr, color=col, lw=2.2, label=f'{name} (AUC {roc_auc_score(d.target, d.p_fusion):.3f})')
ax.plot([0, 1], [0, 1], '--', color='#666666', lw=1)
ax.set(xlabel='False positive rate', ylabel='True positive rate', title='Fusion ROC, three runs (validation)')
ax.legend(fontsize=7, loc='lower right')
plt.tight_layout()
plt.savefig(f'{V2_RUN}/figures/ablation_v1_v2nometa_v2.png', dpi=140)
plt.show()
"""),
md("""
**Reading the ablation**
- The first paired difference isolates the **text-cue T** change, the second isolates **V image metadata**.
- If the image-metadata step carries most of the gain, say so in the report: it is an extension beyond the methodology.
- A difference whose interval includes zero is not evidence of an effect (86 risky validation listings).
"""),
md("""
## 4. Final sealed test: run ONCE, on the v2 run
Only run this when you are ready to commit to v2 as the final model. The test split has not been used by any run. It is scored with
the frozen models, fusion, calibrator and bands, and the run is recorded in the test ledger. A second run on the same model is refused.
The command uses the **explicit v2 run name**, not `latest`, because the ablation above made a newer run.

To run it, type the confirmation phrase exactly into `CONFIRM` and run the cell.
"""),
code("""
CONFIRM = ''   # to run the sealed test, set this to exactly:  RUN THE SEALED TEST ONCE

V2_NAME = os.path.basename(V2_RUN)
LEDGER = 'evaluations/test_ledger.json'
print('v2 run  :', V2_NAME)
if os.path.exists(LEDGER):
    print('ledger  :', [(e['run'], round(e['fusion_roc_auc'], 3)) for e in json.load(open(LEDGER))['test_evaluations']])

if CONFIRM != 'RUN THE SEALED TEST ONCE':
    print('\\nSealed test NOT run (confirmation phrase not set). Nothing was scored.')
elif os.path.exists(f'{V2_RUN}/test_metrics.json'):
    print('\\nTest already scored for this run; showing saved results below.')
else:
    get_ipython().system(f'python -m gl final --run {V2_NAME}')
"""),
code("""
TM = f'{V2_RUN}/test_metrics.json'
if not os.path.exists(TM):
    print('No test results yet (the sealed test has not been run).')
else:
    t = json.load(open(TM)); v = json.load(open(f'{V2_RUN}/validation_metrics.json'))
    f, fv = t['models']['fusion']['roc_auc'], v['models']['fusion']['roc_auc']
    level = 'GOOD' if f['point'] >= 0.75 else 'MINIMUM USEFUL' if f['point'] >= 0.70 else 'BELOW THE BAR'
    print(f"TEST fusion ROC AUC {f['point']:.3f} (95% CI {f['lo']:.3f}-{f['hi']:.3f})  ->  {level}")
    print(f"validation was     {fv['point']:.3f} (95% CI {fv['lo']:.3f}-{fv['hi']:.3f})")
    b = {r['band']: r for r in t['bands']}; bv = {r['band']: r for r in v['bands']}
    for k in ('Low', 'Moderate', 'High'):
        print(f"  {k:9s} test n={b[k]['n']:3d} risky rate {b[k]['risky_rate']:.2f}   (validation n={bv[k]['n']:3d} rate {bv[k]['risky_rate']:.2f})")
    rows = []
    for k in ('B', 'V', 'T', 'text_baseline', 'tabular_ext', 'fusion'):
        a, av = t['models'][k]['roc_auc'], v['models'][k]['roc_auc']
        rows.append({'model': k, 'test AUC': f"{a['point']:.3f} [{a['lo']:.3f}, {a['hi']:.3f}]", 'validation AUC': f"{av['point']:.3f}"})
    display(pd.DataFrame(rows).set_index('model'))

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6))
    ks = ['B', 'V', 'T', 'fusion']
    for j, (m, lab, col) in enumerate([(v, 'validation', '#666666'), (t, 'test (sealed)', '#D55E00')]):
        pts = np.array([m['models'][k]['roc_auc']['point'] for k in ks])
        lo = pts - np.array([m['models'][k]['roc_auc']['lo'] for k in ks])
        hi = np.array([m['models'][k]['roc_auc']['hi'] for k in ks]) - pts
        axes[0].bar(np.arange(len(ks)) + (j - 0.5) * 0.36, pts, 0.36, yerr=[lo, hi], capsize=3, color=col, label=lab)
    for y_, tx, ls in ((0.5, 'chance', '--'), (0.70, 'min useful', ':'), (0.75, 'good', ':')):
        axes[0].axhline(y_, ls=ls, color='black', lw=1)
    axes[0].set_xticks(range(len(ks)), ['B', 'V', 'T', 'FUSION'])
    axes[0].set_ylim(0.4, 0.95); axes[0].set_title('ROC AUC: validation vs sealed test (95% CI)', fontweight='bold'); axes[0].legend(fontsize=8)
    bands = ['Low', 'Moderate', 'High']
    for j, (bb, lab, col) in enumerate([(bv, 'validation', '#666666'), (b, 'test (sealed)', '#D55E00')]):
        axes[1].bar(np.arange(3) + (j - 0.5) * 0.36, [bb[k]['risky_rate'] for k in bands], 0.36, color=col, label=lab)
    axes[1].set_xticks(range(3), bands); axes[1].set_ylim(0, 1)
    axes[1].set_title('Share risky per band (bands fixed on validation)', fontweight='bold'); axes[1].legend(fontsize=8)
    plt.tight_layout(); plt.savefig(f'{V2_RUN}/figures/validation_vs_test.png', dpi=140); plt.show()

    for name in ['config_comparison', 'model_comparison', 'roc', 'precision_recall', 'calibration_compare', 'band_chart',
                 'confusion_flag_moderate_or_high', 'confusion_flag_high_only', 'group_performance']:
        p = f'{V2_RUN}/figures/{name}_test.png'
        if os.path.exists(p):
            display(HTML(f'<h4 style="margin:18px 0 4px">{name.replace("_", " ")} (test)</h4>'))
            display(Image(filename=p))
"""),
md("## 5. Save and download\nEverything is already on Drive in `MyDrive/GuardianLens_runs/`. This downloads the v2 run, the ablation run and the test ledger (no model files)."),
code("""
import shutil
tmp = '/content/run_results_v2_5'
shutil.rmtree(tmp, ignore_errors=True)
for r in (V2_RUN, NM_RUN):
    shutil.copytree(r, f'{tmp}/{os.path.basename(r)}', ignore=shutil.ignore_patterns('xlmr', 'models', '*.joblib'))
if os.path.exists('evaluations/test_ledger.json'):
    shutil.copy('evaluations/test_ledger.json', tmp)
shutil.make_archive('/content/run_results_v2_5', 'zip', tmp)
from google.colab import files
files.download('/content/run_results_v2_5.zip')
"""),
]
nb = {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"provenance": []},
      "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 5}
out = Path(__file__).resolve().parent.parent / "notebooks" / "GuardianLens_Colab_v2_5.ipynb"
out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print("wrote", out)
