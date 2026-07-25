from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "README.md", ROOT / "FIRST_DRAFT_STATUS.md", ROOT / "docs", ROOT / "research"]
FORBIDDEN = {"em dash": "\u2014", "en dash": "\u2013"}


def main() -> int:
    findings: list[str] = []
    for target in TARGETS:
        paths = [target] if target.is_file() else target.rglob("*.md")
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for label, character in FORBIDDEN.items():
                if character in text:
                    findings.append(f"{path.relative_to(ROOT)} contains an {label}")
    if findings:
        print("\n".join(findings))
        return 1
    print("Prose punctuation check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
