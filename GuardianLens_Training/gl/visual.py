"""Methodology signal V: CLIP image-description consistency + SSCD copy detection.

* CLIP consistency: cosine similarity between each listing photo and its title (and a generic
  "a photo of <category>" prompt). Zero-shot, no labels used.
* SSCD copy detection: for each photo, the highest SSCD cosine similarity to any photo of a DIFFERENT
  listing group in the reference corpus. The reference corpus is the TRAIN split's images (recorded in
  the run); same-group photos are excluded so a listing never matches its own reposts.
  Similarity reports reuse inside this corpus only; it cannot show that a photo is universally original.

Embeddings are label-free and cached per listing. Test images are only embedded when `gl final` runs.
"""
from __future__ import annotations

import re
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from .config import path

SSCD_SIZE = 288
MATCH_THRESHOLD = 0.60  # SSCD cosine above which a photo counts as a probable copy (reported, not tuned on test)

FEATURES = ["clip_title_mean", "clip_title_max", "clip_title_min", "clip_category_mean", "clip_title_minus_category",
            "sscd_max", "sscd_mean_max", "sscd_frac_match", "n_images"]
META_FEATURES = ["img_meta_count", "img_min_side", "img_mean_side", "img_mean_kb"]


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def _device() -> str:
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def listing_images(cfg: dict, row, n: int) -> list[Path]:
    root = path(cfg, "images_root")
    primary = root / str(row["primary_image_path"])
    folder = primary.parent
    files = sorted(folder.glob("image_*.jpg")) if folder.exists() else []
    if not files and primary.exists():
        files = [primary]
    if primary in files:
        files = [primary] + [f for f in files if f != primary]
    return files[:n]


def _cache_file(cfg: dict) -> Path:
    return path(cfg, "cache_dir") / f"visual__{_slug(cfg['signals']['visual']['clip_model'])}.npz"


def _load_cache(p: Path) -> dict:
    if not p.exists():
        return {}
    z = np.load(p, allow_pickle=False)
    out, off = {}, 0
    for i, lid in enumerate(z["ids"].tolist()):
        n = int(z["n"][i])
        out[lid] = {"clip": z["clip"][off:off + n].astype(np.float32), "sscd": z["sscd"][off:off + n].astype(np.float32),
                    "title": z["title"][i].astype(np.float32)}
        off += n
    return out


def _save_cache(p: Path, store: dict):
    p.parent.mkdir(parents=True, exist_ok=True)
    ids = list(store)
    d = 512
    clip = np.vstack([store[i]["clip"] for i in ids if len(store[i]["clip"])] or [np.zeros((0, d), np.float32)])
    sscd = np.vstack([store[i]["sscd"] for i in ids if len(store[i]["sscd"])] or [np.zeros((0, d), np.float32)])
    np.savez_compressed(p, ids=np.array(ids), n=np.array([len(store[i]["clip"]) for i in ids]),
                        clip=clip.astype(np.float16), sscd=sscd.astype(np.float16),
                        title=np.vstack([store[i]["title"] for i in ids]).astype(np.float16))


def _ensure_sscd(cfg: dict) -> Path:
    url = cfg["signals"]["visual"]["sscd_url"]
    dst = path(cfg, "cache_dir") / "sscd" / Path(url).name
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(dst)
    return dst


def _clip_text(model, proc, texts: list[str], dev: str) -> np.ndarray:
    import torch
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), 64):
            inp = proc.tokenizer(texts[i:i + 64], padding=True, truncation=True, max_length=77, return_tensors="pt").to(dev)
            v = model.get_text_features(**inp)
            if not torch.is_tensor(v):
                v = v.pooler_output
            out.append(torch.nn.functional.normalize(v, dim=-1).cpu().numpy())
    return np.vstack(out).astype(np.float32)


def extract(cfg: dict, df: pd.DataFrame, log=print) -> dict:
    """Ensure the cache holds CLIP image/title and SSCD embeddings for every listing in df."""
    import torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor

    vc = cfg["signals"]["visual"]
    cache = _cache_file(cfg)
    store = _load_cache(cache)
    missing = df[~df["listing_id"].isin(store)]
    if not len(missing):
        return store
    dev = _device()
    log(f"  visual: embedding {len(missing)} listings with CLIP + SSCD on {dev} ...")
    clip = CLIPModel.from_pretrained(vc["clip_model"]).to(dev).eval()
    proc = CLIPProcessor.from_pretrained(vc["clip_model"])
    sscd = torch.jit.load(str(_ensure_sscd(cfg)), map_location=dev).eval()
    mean = torch.tensor([0.485, 0.456, 0.406], device=dev).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225], device=dev).view(1, 3, 1, 1)

    titles = (missing["title"].fillna("")).tolist()
    title_emb = _clip_text(clip, proc, titles, dev)
    n_per = vc["images_per_listing"]
    bs = vc["batch_size"]
    pending: list[tuple[str, Image.Image]] = []
    acc: dict[str, dict] = {lid: {"clip": [], "sscd": []} for lid in missing["listing_id"]}

    def flush():
        if not pending:
            return
        ims = [im for _, im in pending]
        with torch.no_grad():
            inp = proc(images=ims, return_tensors="pt").to(dev)
            v = clip.get_image_features(**inp)
            if not torch.is_tensor(v):
                v = v.pooler_output
            cv = torch.nn.functional.normalize(v, dim=-1).cpu().numpy()
            x = torch.stack([torch.from_numpy(np.asarray(i.resize((SSCD_SIZE, SSCD_SIZE)), dtype=np.float32) / 255.0)
                             .permute(2, 0, 1) for i in ims]).to(dev)
            sv = torch.nn.functional.normalize(sscd((x - mean) / std), dim=-1).cpu().numpy()
        for (lid, _), c, s in zip(pending, cv, sv):
            acc[lid]["clip"].append(c)
            acc[lid]["sscd"].append(s)
        pending.clear()

    for k, (_, row) in enumerate(missing.iterrows()):
        for f in listing_images(cfg, row, n_per):
            try:
                pending.append((row["listing_id"], Image.open(f).convert("RGB")))
            except Exception:
                continue
            if len(pending) >= bs:
                flush()
        if k and k % 400 == 0:
            log(f"    {k}/{len(missing)} listings")
    flush()
    for lid, t in zip(missing["listing_id"], title_emb):
        a = acc[lid]
        d = 512
        store[lid] = {"clip": np.vstack(a["clip"]) if a["clip"] else np.zeros((0, d), np.float32),
                      "sscd": np.vstack(a["sscd"]) if a["sscd"] else np.zeros((0, d), np.float32), "title": t}
    _save_cache(cache, store)
    return store


_CAT_CACHE: dict = {}


def _category_embeddings(cfg: dict, cats: list[str]) -> dict:
    """CLIP text embedding of 'a photo of <category>', cached in-process (it is rebuilt for every fold)."""
    model = cfg["signals"]["visual"]["clip_model"]
    missing = [c for c in cats if (model, c) not in _CAT_CACHE]
    if missing:
        from transformers import CLIPModel, CLIPProcessor
        dev = _device()
        clip = CLIPModel.from_pretrained(model).to(dev).eval()
        proc = CLIPProcessor.from_pretrained(model)
        for c, v in zip(missing, _clip_text(clip, proc, [f"a photo of {c.lower()}" for c in missing], dev)):
            _CAT_CACHE[(model, c)] = v
        del clip
    return {c: _CAT_CACHE[(model, c)] for c in cats}


def build_features(cfg: dict, store: dict, ref_df: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Per-listing V features. SSCD reference = ref_df's photos, excluding the listing's own group."""
    gcol = cfg["target"]["group_column"]
    cat_emb = _category_embeddings(cfg, sorted(df["category"].fillna("Other").unique()))

    R, Rg, Rid = [], [], []
    for lid, g in zip(ref_df["listing_id"], ref_df[gcol]):
        s = store[lid]["sscd"]
        if len(s):
            R.append(s)
            Rg.extend([g] * len(s))
            Rid.extend([lid] * len(s))
    R = np.vstack(R)
    Rg, Rid = np.array(Rg), np.array(Rid)

    rows = []
    for lid, g, cat in zip(df["listing_id"], df[gcol], df["category"].fillna("Other")):
        e = store[lid]
        n = len(e["clip"])
        r = {"listing_id": lid, "n_images": float(n), "v_available": bool(n)}
        if n:
            st = e["clip"] @ e["title"]
            sc = e["clip"] @ cat_emb[cat]
            r.update(clip_title_mean=st.mean(), clip_title_max=st.max(), clip_title_min=st.min(),
                     clip_category_mean=sc.mean(), clip_title_minus_category=st.mean() - sc.mean())
            sim = e["sscd"] @ R.T
            sim[:, Rg == g] = -1.0
            best = sim.max(axis=1)
            j = int(np.argmax(best))
            r.update(sscd_max=best.max(), sscd_mean_max=best.mean(), sscd_frac_match=float((best >= MATCH_THRESHOLD).mean()),
                     sscd_match_listing=str(Rid[int(sim[j].argmax())]) if best[j] >= MATCH_THRESHOLD else "")
        rows.append(r)
    F = pd.DataFrame(rows).set_index("listing_id")
    return F
