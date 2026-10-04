"""Recovery command: force a fresh annotation-dataset export.

Run this after a refresh failure (see the "annotation_dataset" status in
GET /api/status) to retry without restarting the server. SQLite stays the
only source of truth; this only regenerates data/exports/annotation_dataset/.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guardianlens.annotation_dataset import refresh_annotation_dataset


def main() -> int:
    try:
        result = refresh_annotation_dataset("manual_recovery_script")
    except Exception as exc:
        print(f"Annotation dataset refresh failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    counts = result["counts"]
    print(f"Annotation dataset refreshed at {result['generated_at']}")
    print(f"  output: {result['output_path']}")
    print(
        f"  {counts['source_rows']} source rows, {counts['listings']} listings, "
        f"{counts['images']} images, {counts['approved_annotation_test']} approved pilot rows"
    )
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
