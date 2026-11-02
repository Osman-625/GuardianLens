# Pins that the API tests do not depend on the developer's own .env file.
#
# A developer switches the local API to trained models in .env (GUARDIANLENS_INFERENCE_MODE=trained
# and a model run folder). Loading those models takes minutes, so if the tests read that file, every
# test that creates the app would load them. The conftest in this folder forces stub inference for
# every test; this test fails if it stops doing so.
from api.settings import get_settings


def test_tests_run_in_stub_mode_whatever_the_local_env_file_says() -> None:
    """The settings seen by a test are stub inference and an in-memory database."""
    settings = get_settings()
    assert settings.guardianlens_inference_mode == "stub"
    assert str(settings.guardianlens_database_path) == ":memory:"
