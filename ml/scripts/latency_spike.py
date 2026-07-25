from __future__ import annotations

import argparse
import importlib
import json
import statistics
import time
from pathlib import Path
from typing import Any, Callable, Protocol


class LatencyAdapter(Protocol):
    def load(self) -> None: ...
    def run(self, image_count: int) -> dict[str, float]: ...


class StubAdapter:
    """Harness check only. Results are explicitly invalid for NFR-02 evidence."""

    def load(self) -> None:
        time.sleep(0.01)

    def run(self, image_count: int) -> dict[str, float]:
        started = time.perf_counter()
        sum(index * index for index in range(1000 * image_count))
        total = (time.perf_counter() - started) * 1000
        return {
            "visual_ms": total * 0.45,
            "textual_ms": total * 0.30,
            "behavioural_ms": total * 0.05,
            "fusion_ms": total * 0.05,
            "explanation_ms": total * 0.15,
            "total_ms": total,
        }


def load_adapter(spec: str | None) -> tuple[LatencyAdapter, bool]:
    if not spec:
        return StubAdapter(), False
    module_name, factory_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    factory: Callable[[], LatencyAdapter] = getattr(module, factory_name)
    return factory(), True


def main() -> int:
    parser = argparse.ArgumentParser(description="GuardianLens CPU latency spike harness")
    parser.add_argument("--adapter", help="Python module and factory, for example guardianlens_real:build_adapter")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/latency-spike.json"))
    args = parser.parse_args()

    adapter, evidence_valid = load_adapter(args.adapter)
    load_started = time.perf_counter()
    adapter.load()
    cold_load_ms = (time.perf_counter() - load_started) * 1000

    measurements: dict[str, Any] = {}
    for image_count in (1, 3):
        runs = [adapter.run(image_count) for _ in range(args.runs)]
        stage_names = runs[0].keys()
        measurements[str(image_count)] = {
            stage: {
                "median_ms": statistics.median(run[stage] for run in runs),
                "max_ms": max(run[stage] for run in runs),
            }
            for stage in stage_names
        }

    payload = {
        "cold_load_ms": cold_load_ms,
        "measurements": measurements,
        "evidence_valid_for_nfr02": evidence_valid,
        "verdict": (
            "Compare the real adapter's three-image total against 10000 ms."
            if evidence_valid
            else "INVALID FOR NFR-02: no real CLIP, SSCD, or XLM-RoBERTa adapter was supplied."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
