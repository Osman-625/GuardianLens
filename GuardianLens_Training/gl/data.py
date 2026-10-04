"""Frozen split loading and integrity verification."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import path

SPLITS = ("train", "validation", "test")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_split(cfg: dict, name: str) -> pd.DataFrame:
    if name not in SPLITS:
        raise ValueError(f"unknown split {name!r}")
    df = pd.read_csv(path(cfg, "splits_dir") / f"{name}.csv", keep_default_na=True)
    for col in ("title", "description"):
        df[col] = df[col].fillna("").astype(str)
    return df


def load_unlabelled(cfg: dict, name: str) -> pd.DataFrame:
    """A split read WITHOUT its label or any model input: only identity, group and the image path. Used for the sealed
    test split everywhere except `gl final`, so ordinary code (integrity checks, reports) can never see test labels."""
    cols = [cfg["target"]["id_column"], cfg["target"]["group_column"], "primary_image_path"]
    return pd.read_csv(path(cfg, "splits_dir") / f"{name}.csv", usecols=cols)


def labels(cfg: dict, df: pd.DataFrame) -> np.ndarray:
    return df[cfg["target"]["column"]].to_numpy(dtype=int)


def groups(cfg: dict, df: pd.DataFrame) -> np.ndarray:
    return df[cfg["target"]["group_column"]].to_numpy()


def write_manifest(cfg: dict) -> dict:
    """Record the hash of each split file. Run once when the split is frozen."""
    d = path(cfg, "splits_dir")
    man = {"files": {}, "counts": {}}
    for s in SPLITS:
        man["files"][f"{s}.csv"] = sha256(d / f"{s}.csv")
        if s == "test":   # the sealed split's labels are not read here
            man["counts"][s] = {"rows": int(len(load_unlabelled(cfg, s)))}
            continue
        df = load_split(cfg, s)
        y = labels(cfg, df)
        man["counts"][s] = {"rows": int(len(df)), "risky": int(y.sum()), "legitimate": int((1 - y).sum())}
    (d / "split_manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
    return man


def verify(cfg: dict, check_images: bool = True) -> dict:
    """Integrity report. `ok` is False if anything that would invalidate an experiment is found."""
    d = path(cfg, "splits_dir")
    # the sealed test split is read without labels (identity/group/image path only)
    dfs = {s: (load_unlabelled(cfg, s) if s == "test" else load_split(cfg, s)) for s in SPLITS}
    idc, gc, tc = cfg["target"]["id_column"], cfg["target"]["group_column"], cfg["target"]["column"]
    problems: list[str] = []
    report: dict = {"splits": {}, "problems": problems}

    for s, df in dfs.items():
        if df[idc].duplicated().any():
            problems.append(f"{s}: duplicate listing ids")
        if s == "test":
            report["splits"][s] = {"rows": int(len(df)), "groups": int(df[gc].nunique()), "labels": "sealed, not read"}
            continue
        y = df[tc]
        if not set(y.unique()) <= {0, 1}:
            problems.append(f"{s}: target has values other than 0/1")
        report["splits"][s] = {
            "rows": int(len(df)), "risky": int(y.sum()), "prevalence": round(float(y.mean()), 4),
            "groups": int(df[gc].nunique()),
        }

    for a in SPLITS:
        for b in SPLITS:
            if a < b:
                ids = set(dfs[a][idc]) & set(dfs[b][idc])
                grp = set(dfs[a][gc]) & set(dfs[b][gc])
                if ids:
                    problems.append(f"{a}/{b}: {len(ids)} shared listing ids")
                if grp:
                    problems.append(f"{a}/{b}: {len(grp)} shared groups (leakage)")
    report["group_overlap_free"] = not any("groups" in p or "listing ids" in p for p in problems)

    man_path = d / "split_manifest.json"
    if man_path.exists():
        man = json.loads(man_path.read_text(encoding="utf-8"))
        for fname, want in man["files"].items():
            if sha256(d / fname) != want:
                problems.append(f"{fname}: hash differs from split_manifest.json (split was modified)")
        for sp, want in man.get("counts", {}).items():     # row counts (and train/validation risky counts) must match too
            if sp in report["splits"] and report["splits"][sp]["rows"] != want.get("rows"):
                problems.append(f"{sp}: row count {report['splits'][sp]['rows']} differs from manifest {want.get('rows')}")
            if sp != "test" and sp in report["splits"] and "risky" in want and report["splits"][sp]["risky"] != want["risky"]:
                problems.append(f"{sp}: risky count differs from manifest")
        report["manifest"] = "verified" if not any(("hash differs" in p or "count" in p) for p in problems) else "MISMATCH"
    else:
        problems.append("split_manifest.json missing (run: python -m gl check --freeze)")

    if check_images:
        root = path(cfg, "images_root")
        missing = 0
        for df in dfs.values():
            missing += sum(not (root / str(p)).exists() for p in df["primary_image_path"])
        report["primary_images_missing"] = int(missing)
        if missing:
            problems.append(f"{missing} primary images not found under {root}")

    report["ok"] = not problems
    return report
