"""Collection-only integration: automatic annotation exports are inactive.

The legacy explicit export utility remains available for historical reproducibility.
These callbacks have no database, filesystem, timer, or network side effects.
Existing processes pick up this change only on their next normal start.
"""
from typing import Any


def get_annotation_dataset_status() -> dict[str, Any]:
    return {
        "ok": True, "state": "disabled", "automatic_refresh_enabled": False,
        "trigger": None, "started_at": None, "completed_at": None,
        "output_path": None, "manifest_path": None, "counts": {}, "error": None,
        "reason": "Collection-only workspace. Use the separate frozen-input command for handoff.",
    }


def refresh_annotation_dataset_safely(trigger: str) -> dict[str, Any]:
    return get_annotation_dataset_status()


def schedule_annotation_dataset_refresh(trigger: str) -> None:
    return None
