"""Tabular features: listing/seller fields, text cues, and label-free image metadata.

Deliberately excluded (they are annotation-process artifacts, not things the app can see):
annotation_readiness, validation_status, final_label, final_label_source, evidence_*, image_evidence_used.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .config import path

CONDITION_ORDER = {"poor": 0, "fair": 1, "good": 2, "like_new": 3, "new": 4}
CATEGORICAL = ["platform", "category", "language"]

_URL = re.compile(r"https?://|www\.|\.com\b", re.I)
_PHONE = re.compile(r"(\+?60|0)\s?1\d[\s-]?\d{3,4}[\s-]?\d{3,4}")
_CONTACT = re.compile(r"whats?app|wasap|wassap|wechat|telegram|\bwa\.me|line id|dm me|pm me", re.I)
_PAYMENT = re.compile(r"deposit|bank[- ]?in|transfer|advance|pay first|bayar dulu|cod\b|cash on delivery|touch ?n ?go|tng", re.I)
_URGENT = re.compile(r"urgent|cepat|fast deal|last (piece|unit)|kena jual|must sell|need cash|hari ini", re.I)
_CHEAP = re.compile(r"murah|cheap|clearance|below market|promo|hot deal|sale\b|rm ?\d+ ?only", re.I)
_TRUST = re.compile(r"warranty|waranti|receipt|resit|invoice|original|ori\b|box|sealed", re.I)
_NOREFUND = re.compile(r"no (refund|return|exchange)|tak (refund|return)|final price|no nego", re.I)


def text_cues(title: str, description: str) -> dict[str, float]:
    text = f"{title}\n{description}"
    letters = [c for c in text if c.isalpha()]
    upper = sum(c.isupper() for c in letters)
    return {
        "title_len": len(title),
        "desc_len": len(description),
        "desc_words": len(description.split()),
        "digit_ratio": sum(c.isdigit() for c in text) / max(len(text), 1),
        "upper_ratio": upper / max(len(letters), 1),
        "exclaim": text.count("!"),
        "emoji_like": sum(ord(c) > 0x2600 for c in text),
        "has_url": float(bool(_URL.search(text))),
        "has_phone": float(bool(_PHONE.search(text))),
        "cue_contact": len(_CONTACT.findall(text)),
        "cue_payment": len(_PAYMENT.findall(text)),
        "cue_urgent": len(_URGENT.findall(text)),
        "cue_cheap": len(_CHEAP.findall(text)),
        "cue_trust": len(_TRUST.findall(text)),
        "cue_norefund": len(_NOREFUND.findall(text)),
    }


META_COLS = ["img_meta_count", "img_min_side", "img_mean_side", "img_mean_aspect", "img_mean_kb"]


def _meta_stats(widths, heights, sizes_bytes) -> dict:
    w, h, sz = np.asarray(widths, float), np.asarray(heights, float), np.asarray(sizes_bytes, float)
    side = np.minimum(w, h)
    return {"img_meta_count": float(len(w)), "img_min_side": float(side.min()), "img_mean_side": float(side.mean()),
            "img_mean_aspect": float((w / np.clip(h, 1, None)).mean()), "img_mean_kb": float(sz.mean() / 1024.0)}


def image_metadata(cfg: dict, max_images: int = 3) -> pd.DataFrame:
    """Per-listing image measurements from the FIRST `max_images` photos only (primary first, then file-name order).

    This mirrors what the app can compute from at most `max_images` uploads (the app caps uploads at 3), uses only
    the listing's own images (no cross-listing statistic, so no transductive feature), and the same function
    `image_meta_from_files` computes it from real files for brand-new listings. The old whole-corpus `phash_reuse`
    count was removed (audit finding: it depended on other held-out listings).
    """
    p = path(cfg, "image_meta")
    if not p.exists():
        return pd.DataFrame(columns=["listing_id", *META_COLS])
    im = pd.read_json(p, lines=True)
    im["_file"] = im["storage_path"].astype(str).str.replace("\\", "/", regex=False).str.rsplit("/", n=1).str[-1]
    im = im.sort_values(["listing_id", "is_primary", "_file"], ascending=[True, False, True])
    im = im.groupby("listing_id").head(max_images)
    rows = []
    for lid, g in im.groupby("listing_id"):
        rows.append({"listing_id": lid, **_meta_stats(g["width"], g["height"], g["file_size_bytes"])})
    return pd.DataFrame(rows)


def image_meta_from_files(files) -> dict | None:
    """Same measurements, computed directly from image files (serving path for brand-new listings)."""
    import os

    from PIL import Image
    w, h, sz = [], [], []
    for f in files:
        try:
            with Image.open(f) as im:
                ww, hh = im.size
            w.append(ww)
            h.append(hh)
            sz.append(os.path.getsize(f))
        except Exception:
            continue
    return _meta_stats(w, h, sz) if w else None


def image_meta_for(cfg: dict, df: pd.DataFrame, table: pd.DataFrame | None = None, max_images: int = 3) -> pd.DataFrame:
    """Metadata for every row of df, indexed by listing_id. Listings absent from the frozen table (new listings)
    are measured from their image files, so no listing is silently left blank."""
    from .visual import listing_images
    table = image_metadata(cfg, max_images) if table is None else table
    known = table.set_index("listing_id") if len(table) and "listing_id" in table.columns else pd.DataFrame(columns=META_COLS)
    rows = {}
    for _, r in df.iterrows():
        lid = r["listing_id"]
        if lid in known.index:
            rows[lid] = known.loc[lid, META_COLS].to_dict()
        else:
            m = image_meta_from_files(listing_images(cfg, r, max_images))
            rows[lid] = m if m else {c: np.nan for c in META_COLS}
    out = pd.DataFrame.from_dict(rows, orient="index", columns=META_COLS)
    out.index.name = "listing_id"
    return out


class TabularFeatures:
    """Fit on TRAIN only (category price medians, vocabularies); transform any split."""

    def __init__(self, use_platform: bool = True, image_meta: pd.DataFrame | None = None, parity: bool = False):
        """parity=True keeps only inputs the current app can supply for a brand-new listing: no condition, no
        offline duplicate/reuse flags, no redaction count, no capture-time image count (the first-3-image
        measurements carry a capped count instead)."""
        self.use_platform = use_platform
        self.image_meta = image_meta
        self.parity = parity
        self.vocab: dict[str, list[str]] = {}
        self.cat_price: pd.DataFrame | None = None
        self.global_price: tuple[float, float] = (0.0, 1.0)
        self.columns_: list[str] = []
        self.categorical_mask_: list[bool] = []

    def fit(self, df: pd.DataFrame) -> "TabularFeatures":
        for c in CATEGORICAL:
            self.vocab[c] = sorted(df[c].fillna("unknown").astype(str).unique())
        lp = np.log1p(df["price"].clip(lower=0))
        self.global_price = (float(lp.median()), float(lp.std() or 1.0))
        stats = lp.groupby(df["category"]).agg(["median", "std", "size"])
        stats["std"] = stats["std"].fillna(self.global_price[1]).replace(0, self.global_price[1])
        # shrink small-category medians toward the global median
        k = 10.0
        stats["median"] = (stats["median"] * stats["size"] + self.global_price[0] * k) / (stats["size"] + k)
        self.cat_price = stats[["median", "std"]]
        self.columns_ = list(self.transform(df.head(5)).columns)
        self.categorical_mask_ = [c in CATEGORICAL for c in self.columns_]
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        X = pd.DataFrame(index=df.index)
        price = df["price"].clip(lower=0)
        X["log_price"] = np.log1p(price)
        med = df["category"].map(self.cat_price["median"]).fillna(self.global_price[0])
        std = df["category"].map(self.cat_price["std"]).fillna(self.global_price[1])
        X["price_z_in_category"] = (X["log_price"] - med) / std
        X["price_is_zero"] = (price == 0).astype(float)
        for c in ("account_age_days", "seller_rating", "review_count", "active_listing_count"):
            X[c] = df[c].astype(float)
            X[f"{c}_missing"] = df[c].isna().astype(float)
        X["review_count_log"] = np.log1p(df["review_count"].astype(float))
        if not self.parity:
            X["condition"] = df["condition"].map(CONDITION_ORDER).astype(float)
            X["image_count"] = df["image_count"].astype(float)
            X["reused_image_indicator"] = df["reused_image_indicator"].astype(float)
            X["possible_duplicate"] = (df["duplicate_status"] == "possible_duplicate").astype(float)
            X["redacted_pii_count"] = df["redacted_pii_count"].astype(float)
        cues = pd.DataFrame([text_cues(t, d) for t, d in zip(df["title"], df["description"])], index=df.index)
        X = pd.concat([X, cues], axis=1)
        if self.image_meta is not None and len(self.image_meta):
            im = df[["listing_id"]].merge(self.image_meta, on="listing_id", how="left").drop(columns="listing_id")
            im.index = df.index
            X = pd.concat([X, im], axis=1)
        for c in CATEGORICAL:
            if c == "platform" and not self.use_platform:
                continue
            vocab = self.vocab.get(c) or sorted(df[c].fillna("unknown").astype(str).unique())
            idx = {v: i for i, v in enumerate(vocab)}
            X[c] = df[c].fillna("unknown").astype(str).map(idx).astype(float)  # unseen -> NaN
        return X


class BehaviouralFeatures:
    """Methodology signal B: price, category price ratio, account age, seller rating, review count, active
    listings, plus explicit missingness flags. Category price medians are fitted on the rows passed to `fit`
    (the training rows of each fold), never on validation/test."""

    RAW = ["account_age_days", "seller_rating", "review_count", "active_listing_count"]

    def __init__(self, features: list[str] | None = None):
        self.features = features or ["price", "price_ratio_category", *self.RAW]
        self.cat_median: pd.Series | None = None
        self.global_median: float = 1.0
        self.columns_: list[str] = []

    def fit(self, df: pd.DataFrame) -> "BehaviouralFeatures":
        price = df["price"].clip(lower=0)
        self.global_median = float(max(price.median(), 1.0))
        stats = price.groupby(df["category"]).agg(["median", "size"])
        k = 10.0  # shrink small categories toward the global median
        self.cat_median = (stats["median"] * stats["size"] + self.global_median * k) / (stats["size"] + k)
        self.columns_ = list(self.transform(df.head(3)).columns)
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        X = pd.DataFrame(index=df.index)
        price = df["price"].clip(lower=0)
        if "price" in self.features:
            X["price"] = price
        if "price_ratio_category" in self.features:
            med = df["category"].map(self.cat_median).fillna(self.global_median).clip(lower=1.0)
            X["price_ratio_category"] = price / med
        for c in self.RAW:
            if c in self.features:
                X[c] = df[c].astype(float)
                X[f"{c}_missing"] = df[c].isna().astype(float)
        return X
