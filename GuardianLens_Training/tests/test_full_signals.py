import json

import numpy as np
import pytest

from gl import pipeline as P


def test_V_and_T_signals_end_to_end(workspace):
    """Real CLIP + SSCD on tiny synthetic photos and a tiny random XLM-R: all three signals, 7 configs, sealed test."""
    transformers = pytest.importorskip("transformers")
    try:
        transformers.AutoTokenizer.from_pretrained("xlm-roberta-base")
        transformers.CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    except Exception:
        pytest.skip("models unavailable offline")
    cfg, tmp = workspace
    cfg["signals"]["visual"]["enabled"] = True
    cfg["signals"]["visual"]["include_image_metadata"] = True   # synthetic data has no jsonl: measured from the image files
    cfg["signals"]["textual"]["enabled"] = True
    cfg["references"]["exploratory_tabular"]["enabled"] = False
    run = P.run_all(cfg, "full", None, with_t=True)

    sig = {k: np.load(run / "signals" / f"{k}.npz") for k in ("V", "T", "B")}
    for k, z in sig.items():
        assert len(z["oof"]) == 240 and len(z["val"]) == 90, k
        assert np.isfinite(z["val"]).all(), k
    assert len(list((run / "xlmr").glob("fold*"))) == 3
    import pandas as pd
    vf = pd.read_csv(run / "visual_features_trainval.csv")
    assert vf[["img_meta_count", "img_min_side", "img_mean_side", "img_mean_kb"]].notna().all().all()   # no blanks for any listing
    assert json.loads((run / "train_diagnostics.json").read_text())["V"]["nested_tuning"] is True
    fj = json.loads((run / "fusion.json").read_text())
    assert set(fj["configs"]) == {"V", "T", "B", "V+T", "V+B", "T+B", "V+T+B"}
    for f in ("config_comparison", "visual_feature_dists", "xlmr_training_history", "shap_summary"):
        assert (run / "figures" / f"{f}.png").exists(), f

    P.final_test(cfg, run)
    test = json.loads((run / "test_metrics.json").read_text())
    assert {"V", "T", "B", "fusion"} <= set(test["models"])
    assert test["models"]["V"]["n_scored"] == 90

    # resume: a re-run keeps finished folds
    again = P.train_signal(cfg, run, "T", force=True)
    assert again is not None
