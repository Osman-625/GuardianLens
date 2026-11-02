# Application settings, read from environment variables and the .env file (see .env.example):
# limits for uploads and text, rate limiting, the allowed website origins (used for CORS), the
# session cookie name, and where the SQLite database file lives. `get_settings` returns one cached
# instance.
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    guardianlens_env: str = "development"
    # Whether scores come from the explicit development stubs or from the trained models.
    guardianlens_inference_mode: Literal["stub", "trained"] = "stub"
    # The folder of the trained run to serve (its models, fusion.joblib and run.json).
    guardianlens_model_run_dir: Path | None = None
    # The training workspace whose `gl` package defines the classes the saved models were made from.
    guardianlens_training_workspace: Path = (
        Path(__file__).resolve().parents[2] / "GuardianLens_Training"
    )
    # Origins allowed to call the API from a browser (CORS); the website's address by default. In
    # the environment, write a JSON list or one comma-separated string. NoDecode stops
    # pydantic-settings from forcing JSON first, which would reject the comma-separated form.
    guardianlens_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    # Name of the httpOnly cookie that carries the website visitor's anonymous session.
    guardianlens_session_cookie: str = "guardianlens_session"
    # Upload limits: how many photos per check and the largest size of each, in bytes.
    guardianlens_max_images: int = 10
    guardianlens_max_image_bytes: int = 5 * 1024 * 1024
    guardianlens_title_max_length: int = 500
    guardianlens_description_max_length: int = 5000
    # Category is free text (any category is accepted), but bounded so it cannot be abused.
    guardianlens_category_max_length: int = 80
    # How many checks one session may start per minute, and how many one network address may
    # (higher, because a shared network is many people). Behind a proxy on another machine, start
    # uvicorn with --forwarded-allow-ips=<the proxy's address>; otherwise it ignores the proxy's
    # X-Forwarded-For header and every visitor looks like the proxy.
    guardianlens_rate_limit_per_minute: int = 6
    guardianlens_rate_limit_per_ip_per_minute: int = 30
    # The SQLite file that keeps sessions, assessments and feedback. ":memory:" keeps them only
    # until the server stops (the tests use that). Read it with any SQLite tool for the analysis.
    guardianlens_database_path: Path = (
        Path(__file__).resolve().parents[1] / "data" / "guardianlens.sqlite3"
    )

    @field_validator("guardianlens_allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        """Reads the origins from a JSON list or from one comma-separated string."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [item.strip() for item in text.split(",") if item.strip()]
        return value

    @field_validator("guardianlens_allowed_origins")
    @classmethod
    def refuse_wildcard_origin(cls, value: list[str]) -> list[str]:
        """The API sends credentials (the session cookie), so "*" would let any site read them."""
        if "*" in value:
            raise ValueError(
                "GUARDIANLENS_ALLOWED_ORIGINS must list origins; a wildcard is not allowed "
                "because the API sends credentials."
            )
        return value

    def validate_runtime(self) -> None:
        """Stops the start-up when trained inference is on but the model run folder is not set."""
        if (
            self.guardianlens_inference_mode == "trained"
            and self.guardianlens_model_run_dir is None
        ):
            raise RuntimeError("Set GUARDIANLENS_MODEL_RUN_DIR before enabling trained inference.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Loads and validates the settings once; later calls return the same instance."""
    settings = Settings()
    settings.validate_runtime()
    return settings
