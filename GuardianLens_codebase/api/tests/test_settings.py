# Settings tests: the allowed origins can be written in the environment as a JSON list or as
# comma-separated text. Before, only the JSON form worked and the server refused to start on the
# other, although the code said both were accepted.
from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.settings import Settings


def origins(monkeypatch: pytest.MonkeyPatch, value: str) -> list[str]:
    """Builds Settings from the environment variable alone (no .env file); returns the origins."""
    monkeypatch.setenv("GUARDIANLENS_ALLOWED_ORIGINS", value)
    return Settings(_env_file=None).guardianlens_allowed_origins  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ('["http://localhost:3000"]', ["http://localhost:3000"]),
        ('["https://a.example", "https://b.example"]', ["https://a.example", "https://b.example"]),
        ("https://a.example", ["https://a.example"]),
        ("https://a.example,https://b.example", ["https://a.example", "https://b.example"]),
        (" https://a.example , https://b.example ,", ["https://a.example", "https://b.example"]),
    ],
)
def test_origins_can_be_a_json_list_or_comma_separated(
    monkeypatch: pytest.MonkeyPatch, written: str, expected: list[str]
) -> None:
    """Both spellings give the same list."""
    assert origins(monkeypatch, written) == expected


@pytest.mark.parametrize("written", ["*", '["*"]', "https://a.example,*"])
def test_a_wildcard_origin_is_still_refused(monkeypatch: pytest.MonkeyPatch, written: str) -> None:
    """The API sends cookies, so a wildcard is refused however it is written."""
    with pytest.raises(ValidationError, match="wildcard"):
        origins(monkeypatch, written)


def test_a_broken_json_list_is_refused_with_a_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Text that starts like a JSON list but is not one stops the start-up clearly."""
    with pytest.raises(ValidationError):
        origins(monkeypatch, '["https://a.example"')
