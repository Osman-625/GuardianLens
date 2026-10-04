"""Build dist/GuardianLens_v3_update.zip: only the code + config + notebook that changed (small).

v3 = methodology v2 plus the audit fixes (see docs/AUDIT_RESPONSE.md). The notebook unzips the existing 209 MB package first,
then overlays this zip, so the images are not uploaded again.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from make_colab_package import TOP, package_config_text  # noqa: E402


def main() -> Path:
    out = ROOT / "dist" / "GuardianLens_v3_update.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((ROOT / "gl").glob("*.py")):
            z.write(f, f"{TOP}/gl/{f.name}")
        z.writestr(f"{TOP}/config.yaml", package_config_text())
        z.write(ROOT / "requirements.txt", f"{TOP}/requirements.txt")
        z.write(ROOT / "README.md", f"{TOP}/README.md")
        z.write(ROOT / "docs" / "AUDIT_RESPONSE.md", f"{TOP}/docs/AUDIT_RESPONSE.md")
        z.write(ROOT / "notebooks" / "GuardianLens_Colab_v3.ipynb", f"{TOP}/GuardianLens_Colab_v3.ipynb")
    print(f"{out}  {out.stat().st_size / 1e3:.0f} KB")
    return out


if __name__ == "__main__":
    main()
