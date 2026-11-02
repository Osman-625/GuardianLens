# The timing script runs end to end against the in-process stub API: it submits checks, waits for
# their results, and reports one pair of times per check and a summary against the 10 s budget.
from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import create_app

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "time_checks.py"


def test_the_timing_script_measures_checks_against_the_api() -> None:
    """Two checks give two timings, the summary names the first and the slowest, and it fits."""
    spec = importlib.util.spec_from_file_location("time_checks", SCRIPT)
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    with TestClient(create_app()) as client:
        results = script.measure(client, runs=2, photos=2, pause=0)

    assert len(results) == 2
    assert all(item["wall"] >= item["server"] >= 0 for item in results)
    summary = script.summarise(results)
    assert summary["checks"] == 2
    assert summary["max_wall_s"] >= summary["first_wall_s"]
    assert summary["within_budget"] is True
