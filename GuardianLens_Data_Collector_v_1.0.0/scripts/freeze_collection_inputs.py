"""Create/verify a frozen collection handoff without starting or changing the app."""
from pathlib import Path
import argparse
import json
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from guardianlens.frozen_inputs import freeze, observe, restore_snapshot, verify_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("observe", "create", "verify", "restore"))
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    progress = lambda message: print(message, flush=True)
    if args.command == "observe":
        result = observe(ROOT)
    elif args.command == "create":
        path = freeze(ROOT, progress=progress)
        result = {"snapshot": str(path), "verification": verify_snapshot(path)}
    else:
        if args.snapshot is None:
            parser.error("--snapshot is required")
        if args.command == "verify":
            result = verify_snapshot(args.snapshot)
        else:
            if args.destination is None:
                parser.error("--destination is required")
            result = restore_snapshot(args.snapshot, args.destination, progress)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
