"""Regenerates notebooks/GuardianLens_Colab_v3.ipynb: audit-fixed training, ablation, sensitivity checks, guarded sealed test."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def md(s):
    return {"cell_type": "markdown", "metadata": {}, "source": s.strip("\n").splitlines(True)}


def code(s):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n").splitlines(True)}


def load_ref():
    """v1 / v2 headline numbers, embedded so the notebook does not depend on old runs being present on Drive."""
    out = {}
    for name, rel in (("v1: XLM-R T, plain V", "runs/run_results_v1/validation_metrics.json"),
                      ("v2: text-cue T, V + all image metadata", "runs/run_result_v2/validation_metrics.json")):
        p = ROOT / rel
        if not p.exists():
            continue
        m = json.loads(p.read_text(encoding="utf-8"))["models"]
        out[name] = {k: [round(m[k]["roc_auc"][x], 4) for x in ("point", "lo", "hi")] for k in ("B", "V", "T", "fusion", "tabular_ext")}
    return out


REF = load_ref()

cells = [
md("""
# GuardianLens: Methodology v3 on Google Colab (audit fixes + ablation)

The read-only audit of v1/v2 found real methodology issues. v3 fixes them **before** anything else is trained or tested:

| Audit item | Fix in v3 |
|---|---|
| Whole-corpus `phash_reuse` (depends on other held-out listings) | removed; image measurements use only the listing's own first 3 photos |
| Image metadata joined by listing ID (blank for new listings) | measured from the image files when the listing is not in the frozen table |
| Offline duplicate / reuse / redaction / condition / capture-time image count in the exploratory model | excluded in the default `parity` variant |
| Tuning not nested | hyperparameters re-selected inside every outer fold |
| V's SSCD references in out-of-fold included other held-out folds | rebuilt per fold from that fold's training rows only |
| Test labels visible to ordinary reporting | test split is read without labels everywhere except `gl final` |
| Ambiguous "T collapsed" warning | calibrated single-signal configs are labelled as such |
| Weak resume / provenance checks | per-signal fingerprints, listing IDs and fold IDs saved |

Then it runs, in this order: **(1)** train v3 (text-cue T, V + image measurements), **(2)** the no-metadata ablation,
**(3)** comparisons with the embedded v1 / v2 numbers, **(4)** the audit's sensitivity checks, **(5)** the guarded sealed test.

**Before you start**
1. Upload the new small `GuardianLens_v3_update.zip` to Drive next to `GuardianLens_Colab_Package.zip`. The old v2 update zip is not enough.
2. A T4 GPU helps (CLIP/SSCD embeddings are cached on Drive from the earlier runs, so it is optional).
3. Run the cells top to bottom. Expect roughly 15-25 minutes for both trainings (nested tuning is slower).
"""),
md("## 1. Setup"),
code("""
import subprocess
print(subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True).stdout or 'no GPU attached (fine if the embedding cache is on Drive)')
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
UPD = find('GuardianLens_v3_update.zip')
print('package :', PKG)
print('update  :', UPD)
assert PKG, 'GuardianLens_Colab_Package.zip not found on Drive'
assert UPD, 'GuardianLens_v3_update.zip not found on Drive: upload it next to the package'
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
!python -m gl check | tail -22
!grep -n "nested_tuning\\|variant:" config.yaml
"""),
md("`check` must end with `\"ok\": true`. Note the test split now shows `\"labels\": \"sealed, not read\"`."),
code("""
import json, glob, os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import Image, display, HTML
from sklearn.metrics import roc_auc_score, roc_curve

def runs_with(suffix):
    return sorted(r for r in glob.glob('runs/*') if os.path.isdir(r) and r.endswith(suffix))
"""),
md("""
## 2. Train v3
Signals **B** (behavioural XGBoost), **V** (CLIP + SSCD + first-3-photo measurements), **T** (TF-IDF + text cues), the two references
(text baseline and the production-parity exploratory model), then the seven-configuration fusion, calibration, bands, SHAP and charts.
"""),
code("!python -m gl all --visual-metadata --text-cues --tag colab_v3"),
md("## 3. Ablation: v3 without the image measurements\nIsolates what the image metadata adds. Skips itself if it already ran."),
code("""
if runs_with('_colab_v3_noMeta'):
    print('ablation run already exists, skipping:', runs_with('_colab_v3_noMeta')[-1])
else:
    get_ipython().system('python -m gl all --text-cues --tag colab_v3_noMeta')
"""),
code("""
V3S, NMS = runs_with('_colab_v3'), runs_with('_colab_v3_noMeta')
assert V3S and NMS, 'v3 and v3 no-meta runs not found; run the two training cells above'
V3_RUN, NM_RUN = V3S[-1], NMS[-1]
print('v3 run        :', V3_RUN)
print('v3 no-meta run:', NM_RUN)
m3 = json.load(open(f'{V3_RUN}/validation_metrics.json'))
mn = json.load(open(f'{NM_RUN}/validation_metrics.json'))
"""),
md("## 4. Results against the bar (fixed before the v1 run finished)"),
code("""
NAMES = {'V': 'V Visual', 'T': 'T Textual', 'B': 'B Behavioural', 'text_baseline': 'Text baseline (TF-IDF)',
         'tabular_ext': 'Exploratory tabular (parity)', 'fusion': 'FUSION'}
rows = []
for k, m in m3['models'].items():
    op = m['operating']['max_f1']
    rows.append({'model': NAMES.get(k, k.replace('cfg_', 'config ')), 'ROC AUC': round(m['roc_auc']['point'], 3),
                 '95% CI': f"{m['roc_auc']['lo']:.3f}-{m['roc_auc']['hi']:.3f}", 'PR AUC': round(m['pr_auc']['point'], 3),
                 'F1': round(op['f1'], 3), 'precision': round(op['precision'], 3), 'recall': round(op['recall'], 3)})
display(pd.DataFrame(rows).set_index('model'))
display(pd.DataFrame(m3['bands']).set_index('band')[['n', 'risky', 'risky_rate']])

f = m3['models']['fusion']['roc_auc']
level = 'GOOD' if f['point'] >= 0.75 else 'MINIMUM USEFUL' if f['point'] >= 0.70 else 'BELOW THE BAR'
b = {r['band']: r for r in m3['bands']}
print(f"\\nv3 fusion ROC AUC {f['point']:.3f} (95% CI {f['lo']:.3f}-{f['hi']:.3f})  ->  {level}   [bar: >=0.70 minimum, >=0.75 good]")
print(f"  Low band risky rate  {b['Low']['risky_rate']:.2f} (bar <= 0.15, n={b['Low']['n']}) | High band {b['High']['risky_rate']:.2f} (bar >= 0.60, n={b['High']['n']})")
print('  risky rate rises Low -> High:', b['Low']['risky_rate'] <= b['Moderate']['risky_rate'] <= b['High']['risky_rate'])
for k, v in m3['fusion_vs_single'].items():
    d = v['roc_auc']
    print(f"  fusion vs {k}: AUC difference {d['point']:+.3f} (95% CI {d['lo']:+.3f} to {d['hi']:+.3f})")
"""),
code("""
REF = __REF__
RUNS = dict(REF)
RUNS['v3 no-meta: text-cue T, plain V'] = {k: [mn['models'][k]['roc_auc'][x] for x in ('point', 'lo', 'hi')] for k in ('B', 'V', 'T', 'fusion', 'tabular_ext')}
RUNS['v3: text-cue T, V + first-3-photo measurements'] = {k: [m3['models'][k]['roc_auc'][x] for x in ('point', 'lo', 'hi')] for k in ('B', 'V', 'T', 'fusion', 'tabular_ext')}
keys = ['B', 'V', 'T', 'fusion']
cols = ['#999999', '#E69F00', '#56B4E9', '#D55E00', '#009E73', '#CC79A7']
fig, ax = plt.subplots(figsize=(12, 5.2))
n = len(RUNS); w = 0.8 / n
for j, ((name, d), col) in enumerate(zip(RUNS.items(), cols)):
    pts = np.array([d[k][0] for k in keys]); lo = pts - np.array([d[k][1] for k in keys]); hi = np.array([d[k][2] for k in keys]) - pts
    x = np.arange(len(keys)) + (j - (n - 1) / 2) * w
    ax.bar(x, pts, w, yerr=[lo, hi], capsize=2, color=col, label=name)
    for xi, p in zip(x, pts):
        ax.text(xi, 0.42, f'{p:.2f}', ha='center', color='white', fontsize=7, fontweight='bold', rotation=90)
for y_, t, ls in ((0.5, 'chance', '--'), (0.70, 'minimum useful', ':'), (0.75, 'good', ':')):
    ax.axhline(y_, ls=ls, color='black', lw=1); ax.text(3.5, y_ + 0.004, t, fontsize=8, ha='right')
ax.set_xticks(range(len(keys)), ['B behavioural', 'V visual', 'T textual', 'FUSION'])
ax.set_ylim(0.4, 0.9); ax.set_ylabel('Validation ROC AUC')
ax.set_title('Methodology v1 -> v2 -> v3 (95% CI, validation)', fontweight='bold'); ax.legend(fontsize=7, loc='upper left')
plt.tight_layout(); plt.savefig(f'{V3_RUN}/figures/methodology_versions.png', dpi=140); plt.show()
print('v1 and v2 numbers are embedded reference values (produced before the audit fixes).')
""".replace("__REF__", json.dumps(REF))),
code("""
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

p, lo, hi = paired_auc_diff(V3_RUN, NM_RUN)
print(f'Effect of the image measurements on the fusion (v3 minus v3 no-meta): {p:+.3f}  [{lo:+.3f}, {hi:+.3f}]  ->',
      'real' if lo > 0 else 'not distinguishable from zero' if hi >= 0 else 'worse')
"""),
md("""
## 5. The audit's sensitivity checks
- Do the results hold **without the listings that have 11+ captured images** (95% risky in train; all Carousell, one capture day)?
- Do they hold **within each platform**?
"""),
code("""
va = pd.read_csv('data/splits/validation.csv', usecols=['listing_id', 'image_count'])
def sens(run, label):
    p = pd.read_csv(f'{run}/val_predictions.csv').merge(va, on='listing_id')
    hi = p.image_count >= 11
    def auc(d, c):
        d = d.dropna(subset=[c])
        return round(roc_auc_score(d.target, d[c]), 3) if d.target.nunique() > 1 and len(d) > 20 else float('nan')
    rows = []
    for c in ['p_B', 'p_V', 'p_T', 'p_fusion', 'p_tabular_ext']:
        if c in p:
            rows.append({'run': label, 'model': c[2:], 'all': auc(p, c), f'without 11+ images (drops {int(hi.sum())})': auc(p[~hi], c),
                         'carousell': auc(p[p.platform == 'carousell'], c), 'mudah': auc(p[p.platform == 'mudah'], c)})
    return pd.DataFrame(rows)
display(pd.concat([sens(V3_RUN, 'v3'), sens(NM_RUN, 'v3 no-meta')]).set_index(['run', 'model']))
print('Mudah has only 14 risky validation listings: treat its numbers as indicative.')
"""),
code("""
ORDER = ['dataset_overview', 'config_comparison', 'model_comparison', 'roc', 'precision_recall', 'score_distributions',
         'calibration_compare', 'band_chart', 'threshold_sweep_fusion', 'confusion_flag_moderate_or_high',
         'confusion_flag_high_only', 'group_performance', 'stacker_weights', 'shap_summary', 'visual_feature_dists']
for name in ORDER:
    f = f'{V3_RUN}/figures/{name}.png'
    if os.path.exists(f):
        display(HTML(f'<h4 style="margin:18px 0 4px">{name.replace("_", " ")}</h4>'))
        display(Image(filename=f))
"""),
md("""
## 6. Final sealed test
**Use `GuardianLens_Colab_final.ipynb` for the real test:** the chosen final model is the `colab_v3_noMeta` run, not this metadata run. The cells below are kept only as a reference.

The test split is still sealed: v3's integrity checks and reports read it without labels, and no run has scored it. Only run this when you
are ready to commit to v3 as the final model. A second run on the same model is refused. The command uses the **explicit v3 run name**
because the ablation made a newer run. Set `CONFIRM` to exactly `RUN THE SEALED TEST ONCE` and run the cell.
"""),
code("""
CONFIRM = ''   # to run the sealed test, set this to exactly:  RUN THE SEALED TEST ONCE

V3_NAME = os.path.basename(V3_RUN)
LEDGER = 'evaluations/test_ledger.json'
print('v3 run  :', V3_NAME)
if os.path.exists(LEDGER):
    print('ledger  :', [(e['run'], round(e['fusion_roc_auc'], 3)) for e in json.load(open(LEDGER))['test_evaluations']])
if CONFIRM != 'RUN THE SEALED TEST ONCE':
    print('\\nSealed test NOT run (confirmation phrase not set). Nothing was scored.')
elif os.path.exists(f'{V3_RUN}/test_metrics.json'):
    print('\\nTest already scored for this run; showing saved results below.')
else:
    get_ipython().system(f'python -m gl final --run {V3_NAME}')
"""),
code("""
TM = f'{V3_RUN}/test_metrics.json'
if not os.path.exists(TM):
    print('No test results yet (the sealed test has not been run).')
else:
    t = json.load(open(TM))
    f, fv = t['models']['fusion']['roc_auc'], m3['models']['fusion']['roc_auc']
    level = 'GOOD' if f['point'] >= 0.75 else 'MINIMUM USEFUL' if f['point'] >= 0.70 else 'BELOW THE BAR'
    print(f"TEST fusion ROC AUC {f['point']:.3f} (95% CI {f['lo']:.3f}-{f['hi']:.3f})  ->  {level}")
    print(f"validation was     {fv['point']:.3f} (95% CI {fv['lo']:.3f}-{fv['hi']:.3f})")
    bt = {r['band']: r for r in t['bands']}; bv = {r['band']: r for r in m3['bands']}
    for k in ('Low', 'Moderate', 'High'):
        print(f"  {k:9s} test n={bt[k]['n']:3d} risky rate {bt[k]['risky_rate']:.2f}   (validation n={bv[k]['n']:3d} rate {bv[k]['risky_rate']:.2f})")
    display(pd.DataFrame([{'model': k, 'test AUC': f"{t['models'][k]['roc_auc']['point']:.3f} [{t['models'][k]['roc_auc']['lo']:.3f}, {t['models'][k]['roc_auc']['hi']:.3f}]",
                           'validation AUC': f"{m3['models'][k]['roc_auc']['point']:.3f}"} for k in ('B', 'V', 'T', 'text_baseline', 'tabular_ext', 'fusion')]).set_index('model'))
    for name in ['config_comparison', 'model_comparison', 'roc', 'precision_recall', 'calibration_compare', 'band_chart',
                 'confusion_flag_moderate_or_high', 'confusion_flag_high_only', 'group_performance']:
        p = f'{V3_RUN}/figures/{name}_test.png'
        if os.path.exists(p):
            display(HTML(f'<h4 style="margin:18px 0 4px">{name.replace("_", " ")} (test)</h4>'))
            display(Image(filename=p))
"""),
md("## 7. Save and download\nEverything is already on Drive in `MyDrive/GuardianLens_runs/`. This downloads the v3 run, the ablation run and the test ledger (no model files)."),
code("""
import shutil
tmp = '/content/run_results_v3'
shutil.rmtree(tmp, ignore_errors=True)
for r in (V3_RUN, NM_RUN):
    shutil.copytree(r, f'{tmp}/{os.path.basename(r)}', ignore=shutil.ignore_patterns('xlmr', 'models', '*.joblib'))
if os.path.exists('evaluations/test_ledger.json'):
    shutil.copy('evaluations/test_ledger.json', tmp)
shutil.make_archive('/content/run_results_v3', 'zip', tmp)
from google.colab import files
files.download('/content/run_results_v3.zip')
"""),
]
nb = {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"provenance": []},
      "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 5}
out = ROOT / "notebooks" / "GuardianLens_Colab_v3.ipynb"
out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print("wrote", out, "| embedded reference runs:", list(REF))
