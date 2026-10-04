"""Regenerates notebooks/GuardianLens_Colab_final.ipynb: the sealed test, run once, on the frozen v3 no-metadata run."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def md(s):
    return {"cell_type": "markdown", "metadata": {}, "source": s.strip("\n").splitlines(True)}


def code(s):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": s.strip("\n").splitlines(True)}


cells = [
md("""
# GuardianLens: final sealed test (run once)

**Frozen model:** the `colab_v3_noMeta` run: signals B (XGBoost), V (CLIP + SSCD, no image metadata), T (TF-IDF + text cues),
out-of-fold logistic-regression fusion, sigmoid calibration, Low/Moderate/High bands. Chosen because adding image measurements changed the
fusion by -0.005 [-0.017, +0.007] (nothing), so the methodology-pure version is kept; validation fusion ROC AUC 0.706.

No hyperparameter, threshold or band is changed here. The test split has never been scored. This notebook scores it **once**; a second
run on the same model is refused and recorded in the ledger. Do not run it again hoping for a different result.

**Before you start:** `GuardianLens_Colab_Package.zip` and `GuardianLens_v3_update.zip` must be on Drive (same as the v3 notebook), and the
`colab_v3_noMeta` run must still be in `MyDrive/GuardianLens_runs/`.
"""),
md("## 1. Setup"),
code("""
import subprocess
print(subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True).stdout or 'no GPU attached (fine; a T4 only speeds up embedding the test photos)')
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

PKG, UPD = find('GuardianLens_Colab_Package.zip'), find('GuardianLens_v3_update.zip')
print('package :', PKG); print('update  :', UPD)
assert PKG and UPD, 'package or v3 update zip not found on Drive'
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
"""),
md("## 2. Locate the frozen run and show its validation result"),
code("""
import json, os, glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import Image, display, HTML

cands = sorted(r for r in glob.glob('runs/*') if os.path.isdir(r) and r.endswith('_colab_v3_noMeta'))
assert cands, 'the colab_v3_noMeta run was not found in MyDrive/GuardianLens_runs'
RUN = cands[-1]
NAME = os.path.basename(RUN)
for f in ('fusion.joblib', 'models/B.joblib', 'models/V.joblib', 'models/T.joblib', 'validation_metrics.json'):
    assert os.path.exists(f'{RUN}/{f}'), f'{RUN}/{f} is missing'
cfgd = json.load(open(f'{RUN}/run.json'))['config']['signals']
assert not cfgd['visual'].get('include_image_metadata'), 'this is not the no-metadata run'
assert cfgd['textual'].get('impl') == 'cues', 'T is not the text-cue signal'
val = json.load(open(f'{RUN}/validation_metrics.json'))
f = val['models']['fusion']['roc_auc']
print('frozen run:', NAME)
print(f"validation fusion ROC AUC {f['point']:.3f} (95% CI {f['lo']:.3f}-{f['hi']:.3f})")
print('bands (validation):', [(r['band'], r['n'], round(r['risky_rate'], 2)) for r in val['bands']])
LEDGER = 'evaluations/test_ledger.json'
if os.path.exists(LEDGER):
    print('ledger so far:', [(e['run'], round(e['fusion_roc_auc'], 3)) for e in json.load(open(LEDGER))['test_evaluations']])
else:
    print('ledger: empty (the test split has never been scored)')
"""),
md("""
## 3. Run the sealed test: once
Set `CONFIRM` to exactly `RUN THE SEALED TEST ONCE` and run the cell. If it is left empty, nothing is scored.
"""),
code("""
CONFIRM = ''   # to run the sealed test, set this to exactly:  RUN THE SEALED TEST ONCE

if CONFIRM != 'RUN THE SEALED TEST ONCE':
    print('Sealed test NOT run (confirmation phrase not set). Nothing was scored.')
elif os.path.exists(f'{RUN}/test_metrics.json'):
    print('Test already scored for this run; showing the saved results below.')
else:
    get_ipython().system(f'python -m gl final --run {NAME}')
"""),
md("## 4. Test results against the bar and against validation"),
code("""
TM = f'{RUN}/test_metrics.json'
if not os.path.exists(TM):
    print('No test results yet (the sealed test has not been run).')
else:
    def auc(y, s):
        y = np.asarray(y); r = pd.Series(np.asarray(s, float)).rank().to_numpy(); n1 = int(y.sum()); n0 = len(y) - n1
        return (r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
    t = json.load(open(TM))
    ft, fv = t['models']['fusion']['roc_auc'], val['models']['fusion']['roc_auc']
    level = 'GOOD' if ft['point'] >= 0.75 else 'MINIMUM USEFUL' if ft['point'] >= 0.70 else 'BELOW THE BAR'
    print(f"TEST fusion ROC AUC {ft['point']:.3f} (95% CI {ft['lo']:.3f}-{ft['hi']:.3f})  ->  {level}   [bar: >=0.70 minimum, >=0.75 good]")
    print(f"validation was     {fv['point']:.3f} (95% CI {fv['lo']:.3f}-{fv['hi']:.3f})")
    bt = {r['band']: r for r in t['bands']}; bv = {r['band']: r for r in val['bands']}
    for k in ('Low', 'Moderate', 'High'):
        print(f"  {k:9s} test n={bt[k]['n']:3d} risky rate {bt[k]['risky_rate']:.2f}   (validation n={bv[k]['n']:3d} rate {bv[k]['risky_rate']:.2f})")
    print('  bar: Low <= 0.15, High >= 0.60, rate rises Low -> High:', bt['Low']['risky_rate'] <= bt['Moderate']['risky_rate'] <= bt['High']['risky_rate'])
    rows = [{'model': k, 'test AUC': f"{t['models'][k]['roc_auc']['point']:.3f} [{t['models'][k]['roc_auc']['lo']:.3f}, {t['models'][k]['roc_auc']['hi']:.3f}]",
             'validation AUC': f"{val['models'][k]['roc_auc']['point']:.3f}"} for k in ('B', 'V', 'T', 'text_baseline', 'tabular_ext', 'fusion')]
    display(pd.DataFrame(rows).set_index('model'))
    for k, v in t['fusion_vs_single'].items():
        d = v['roc_auc']; print(f"  fusion vs {k}: AUC difference {d['point']:+.3f} (95% CI {d['lo']:+.3f} to {d['hi']:+.3f})")
    P = pd.read_csv(f'{RUN}/test_predictions.csv')
    plat = (P.platform == 'carousell').astype(float)
    print(f"\\nplatform-only AUC on test {auc(P.target, plat):.3f} | fusion {auc(P.target, P.p_fusion):.3f}")
    for p in ('carousell', 'mudah'):
        s = P[P.platform == p]; print(f"  {p}: n={len(s)} risky={int(s.target.sum())} fusion AUC {auc(s.target, s.p_fusion):.3f}")

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6))
    ks = ['B', 'V', 'T', 'fusion']
    for j, (m, lab, col) in enumerate([(val, 'validation', '#666666'), (t, 'test (sealed)', '#D55E00')]):
        pts = np.array([m['models'][k]['roc_auc']['point'] for k in ks])
        lo = pts - np.array([m['models'][k]['roc_auc']['lo'] for k in ks]); hi = np.array([m['models'][k]['roc_auc']['hi'] for k in ks]) - pts
        axes[0].bar(np.arange(len(ks)) + (j - 0.5) * 0.36, pts, 0.36, yerr=[lo, hi], capsize=3, color=col, label=lab)
    for y_ in (0.5, 0.70, 0.75):
        axes[0].axhline(y_, ls=':' if y_ > 0.5 else '--', color='black', lw=1)
    axes[0].set_xticks(range(len(ks)), ['B', 'V', 'T', 'FUSION']); axes[0].set_ylim(0.4, 0.95); axes[0].legend(fontsize=8)
    axes[0].set_title('ROC AUC: validation vs sealed test (95% CI)', fontweight='bold')
    bands = ['Low', 'Moderate', 'High']
    for j, (bb, lab, col) in enumerate([(bv, 'validation', '#666666'), (bt, 'test (sealed)', '#D55E00')]):
        axes[1].bar(np.arange(3) + (j - 0.5) * 0.36, [bb[k]['risky_rate'] for k in bands], 0.36, color=col, label=lab)
    axes[1].set_xticks(range(3), bands); axes[1].set_ylim(0, 1); axes[1].legend(fontsize=8)
    axes[1].set_title('Share risky per band (bands fixed on validation)', fontweight='bold')
    plt.tight_layout(); plt.savefig(f'{RUN}/figures/validation_vs_test.png', dpi=140); plt.show()
    for name in ['config_comparison', 'model_comparison', 'roc', 'precision_recall', 'calibration_compare', 'band_chart',
                 'confusion_flag_moderate_or_high', 'confusion_flag_high_only', 'group_performance']:
        p = f'{RUN}/figures/{name}_test.png'
        if os.path.exists(p):
            display(HTML(f'<h4 style="margin:18px 0 4px">{name.replace("_", " ")} (test)</h4>')); display(Image(filename=p))
"""),
md("## 5. Save and download\nThe run (now including the test results) is already on Drive. This downloads the report, charts, test predictions and the ledger (no model files)."),
code("""
import shutil
tmp = '/content/final_test_results'
shutil.rmtree(tmp, ignore_errors=True)
shutil.copytree(RUN, f'{tmp}/{NAME}', ignore=shutil.ignore_patterns('xlmr', 'models', '*.joblib'))
if os.path.exists('evaluations/test_ledger.json'):
    shutil.copy('evaluations/test_ledger.json', tmp)
shutil.make_archive('/content/final_test_results', 'zip', tmp)
from google.colab import files
files.download('/content/final_test_results.zip')
"""),
]
nb = {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"provenance": []},
      "kernelspec": {"name": "python3", "display_name": "Python 3"}, "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 5}
out = ROOT / "notebooks" / "GuardianLens_Colab_final.ipynb"
out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print("wrote", out)
