# Prose punctuation check: the project's Markdown (the README, docs, and research folders) must
# not contain em dashes or en dashes. It prints the offending files and exits with 1 if any are
# found, so CI can fail on it.
from __future__ import annotations

from pathlib import Path

# The repository root (this file lives in scripts/) and the Markdown that is checked.
ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "README.md", ROOT / "docs", ROOT / "research"]
# The characters that are not allowed, by name (written as escapes so this file stays plain ASCII).
FORBIDDEN = {"em dash": "\u2014", "en dash": "\u2013"}


def main() -> int:
    """Scans the Markdown files and returns 0 when clean, 1 when a forbidden dash is found."""
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
