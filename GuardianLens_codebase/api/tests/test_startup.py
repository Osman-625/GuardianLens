# Start-up test: a configuration the server cannot serve must stop it at start-up, with a clear
# message, instead of letting it run and fail every request.
from __future__ import annotations

import pytest

from api.settings import Settings


def test_trained_inference_without_a_model_folder_stops_the_start_up() -> None:
    """Trained scores need the saved run: with no folder set, start-up names the missing setting."""
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, guardianlens_inference_mode="trained"
    )
    with pytest.raises(RuntimeError, match="GUARDIANLENS_MODEL_RUN_DIR"):
        settings.validate_runtime()
