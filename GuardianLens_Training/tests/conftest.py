import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gl import data as D  # noqa: E402
from gl.config import load_config  # noqa: E402


def make_split(n, seed, start):
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < 0.3).astype(int)
    rows = []
    for i in range(n):
        risky = y[i]
        rows.append({
            "listing_id": f"L{start + i}", "platform": rng.choice(["carousell", "mudah"]),
            "category": rng.choice(["Phones", "Laptops", "Audio"]),
            "title": "urgent cheap phone" if risky and rng.random() < 0.6 else "used item for sale",
            "description": "whatsapp me deposit first" if risky and rng.random() < 0.5 else "good condition, nego",
            "condition": rng.choice(["good", "new", "fair"]), "price": float(rng.lognormal(5 + 0.5 * risky, 1)),
            "language": "en", "account_age_days": float(rng.integers(10, 3000)) if rng.random() > 0.3 else np.nan,
            "seller_rating": 4.5 + rng.random() / 2 - 0.4 * risky, "review_count": float(rng.integers(0, 100)),
            "active_listing_count": float(rng.integers(0, 40)), "image_count": int(rng.integers(1, 6) + 2 * risky),
            "reused_image_indicator": bool(risky and rng.random() < 0.4), "duplicate_status": "unique",
            "redacted_pii_count": 0, "primary_image_path": f"images/x/L{start + i}/image_001.jpg",
            "group_id": f"g{start + i}", "target": int(risky),
        })
    return pd.DataFrame(rows)


@pytest.fixture()
def workspace(tmp_path):
    """Synthetic frozen split + tiny images in a temp dir, config pointed at it. Fast signals only by default."""
    cfg = copy.deepcopy(load_config())
    cfg["_root"] = str(tmp_path)
    cfg["paths"].update(splits_dir="splits", cache_dir="cache", runs_dir="runs", ledger="evaluations/ledger.json",
                        images_root="imgs", image_meta="imgs/none.jsonl")
    cfg["signals"]["visual"].update(enabled=False, images_per_listing=1, batch_size=16)
    cfg["signals"]["textual"].update(enabled=False, tiny=True, epochs=2, batch_size=16, max_length=48, patience=2,
                                     learning_rate=1e-3, inner_val_fraction=0.2)
    cfg["cv"].update(folds=3, tune_folds=2)
    cfg["evaluation"]["bootstrap_resamples"] = 60
    (tmp_path / "splits").mkdir()
    rng = np.random.default_rng(1)
    start = 0
    for name, n in (("train", 240), ("validation", 90), ("test", 90)):
        df = make_split(n, {"train": 11, "validation": 22, "test": 33}[name], start)
        start += n
        df.to_csv(tmp_path / "splits" / f"{name}.csv", index=False)
        for p, risky in zip(df["primary_image_path"], df["target"]):
            f = tmp_path / "imgs" / p
            f.parent.mkdir(parents=True, exist_ok=True)
            arr = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
            arr[..., 0] = np.clip(arr[..., 0] + 40 * risky, 0, 255)
            Image.fromarray(arr).save(f, "JPEG")
    D.write_manifest(cfg)
    return cfg, tmp_path
