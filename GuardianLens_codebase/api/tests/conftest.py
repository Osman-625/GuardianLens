# Test setup shared by every API test: stub inference and an in-memory database, whatever the
# developer's own .env file says.
#
# The API reads its settings from the environment and from .env. A developer switches the local
# API to the trained models in .env, and loading them takes minutes, so tests that read that file
# would load the models every time they create the app. Environment variables take precedence over
# .env, so setting them here makes the tests behave the same on every machine. Tests that need
# other settings (for example the trained-model tests) build their own Settings explicitly or
# override these variables with monkeypatch, which wins over this fixture.
from __future__ import annotations

from collections.abc import Iterator

import pytest

from api.settings import get_settings


@pytest.fixture(autouse=True)
def stub_inference_for_every_test(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Forces stub inference and an in-memory database for the length of each test."""
    monkeypatch.setenv("GUARDIANLENS_INFERENCE_MODE", "stub")
    monkeypatch.setenv("GUARDIANLENS_DATABASE_PATH", ":memory:")
    # Settings are cached after the first read: clear before (so these values are used) and after
    # (so they are not carried into whatever runs next).
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
