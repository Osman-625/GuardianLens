from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> dict:
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg["_root"] = str(cfg_path.resolve().parent)
    return cfg


def path(cfg: dict, key: str) -> Path:
    """Resolve a `paths:` entry against the config file's directory."""
    return (Path(cfg["_root"]) / cfg["paths"][key]).resolve()
