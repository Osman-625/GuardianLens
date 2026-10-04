"""Build dist/GuardianLens_Colab_Package.zip: code + frozen splits + a slim copy of the images.

Only the photos the pipeline actually embeds (CLIP + SSCD) (first 3 per listing, primary first) are included, resized
to max 512 px, so the upload is small. Image metadata (original sizes/hashes) is kept verbatim, so the
tabular image features are identical to a local run.
"""
from __future__ import annotations

import sys
import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gl import data as D  # noqa: E402
from gl.config import load_config, path  # noqa: E402
from gl.visual import listing_images  # noqa: E402

MAX_SIDE = 512
TOP = "GuardianLens_Colab"


def package_config_text() -> str:
    """config.yaml with the paths rewritten for the unzipped package layout (images next to the code)."""
    t = (ROOT / "config.yaml").read_text(encoding="utf-8")
    t = t.replace("images_root: ../GuardianLens_Approved_Dataset", "images_root: .")
    t = t.replace("image_meta: ../GuardianLens_Approved_Dataset/approved_images.jsonl", "image_meta: approved_images.jsonl")
    assert "images_root: ." in t and "image_meta: approved_images.jsonl" in t
    return t


def main() -> Path:
    cfg = load_config()
    out = ROOT / "dist" / "GuardianLens_Colab_Package.zip"
    out.parent.mkdir(exist_ok=True)
    img_root = path(cfg, "images_root")
    n_img = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((ROOT / "gl").glob("*.py")):
            z.write(f, f"{TOP}/gl/{f.name}")
        for name in ("requirements.txt", "README.md"):
            z.write(ROOT / name, f"{TOP}/{name}")
        z.write(ROOT / "notebooks" / "GuardianLens_Colab.ipynb", f"{TOP}/GuardianLens_Colab.ipynb")
        z.write(ROOT / "docs" / "COLAB_MCP.md", f"{TOP}/docs/COLAB_MCP.md")
        for f in sorted((ROOT / "data" / "splits").glob("*")):
            if f.name != "source_manifest_v1.json":
                z.write(f, f"{TOP}/data/splits/{f.name}")
        cfg_text = package_config_text()
        z.writestr(f"{TOP}/config.yaml", cfg_text)
        z.write(path(cfg, "image_meta"), f"{TOP}/approved_images.jsonl")
        seen = set()
        for split in D.SPLITS:
            df = D.load_split(cfg, split)
            for _, row in df.iterrows():
                for f in listing_images(cfg, row, cfg["signals"]["visual"]["images_per_listing"]):
                    rel = f.relative_to(img_root).as_posix()
                    if rel in seen:
                        continue
                    seen.add(rel)
                    with Image.open(f) as im:
                        im = im.convert("RGB")
                        im.thumbnail((MAX_SIDE, MAX_SIDE))
                        buf = BytesIO()
                        im.save(buf, "JPEG", quality=85)
                    z.writestr(f"{TOP}/{rel}", buf.getvalue())
                    n_img += 1
    print(f"{out}  {out.stat().st_size / 1e6:.0f} MB, {n_img} images")
    return out


if __name__ == "__main__":
    main()
