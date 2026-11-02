# Secret scan: looks through the project's text files for things that must never be committed
# (a JSON web token, a private key, or an API key written into code). It prints the matching files
# and exits with 1 if any are found, so CI can fail on it.
from __future__ import annotations

import re
from pathlib import Path

# The repository root (this file lives in scripts/), the folders that are never scanned, and the
# kinds of file that are.
ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", ".conda", "node_modules", ".next", "runtime"}
TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".sql",
    ".txt",
    ".example",
}
# One pattern per kind of secret, by the name used in the report.
PATTERNS = {
    "JSON web token": re.compile(r"eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}"),
    "Generic private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "Common API key assignment": re.compile(
        r"(?i)(api[_-]?key|secret[_-]?key|service[_-]?role[_-]?key)\s*[=:]\s*['\"][^'\"]{12,}['\"]"
    ),
}


def iter_files():
    """Yields each text file under the repository root, skipping the folders in SKIP_PARTS."""
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.name == ".env.example" or path.suffix in TEXT_SUFFIXES:
            yield path


def main() -> int:
    """Scans every text file and returns 0 when clean, 1 when a possible secret is found."""
    findings: list[str] = []
    for path in iter_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(ROOT)}: {name}")
    if findings:
        print("Potential secrets found:")
        print("\n".join(findings))
        return 1
    print("Secret scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
