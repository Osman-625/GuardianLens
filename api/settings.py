from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    guardianlens_env: str = "development"
    guardianlens_stub_mode: bool = True
    guardianlens_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    guardianlens_session_cookie: str = "guardianlens_session"
    guardianlens_max_images: int = 3
    guardianlens_max_image_bytes: int = 5 * 1024 * 1024
    guardianlens_title_max_length: int = 180
    guardianlens_description_max_length: int = 5000
    guardianlens_rate_limit_per_minute: int = 6
    guardianlens_dev_admin_token: str | None = None

    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_anon_key: str | None = None

    @field_validator("guardianlens_allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def validate_runtime(self) -> None:
        if self.guardianlens_stub_mode:
            return
        missing = [
            name
            for name, value in {
                "SUPABASE_URL": self.supabase_url,
                "SUPABASE_SERVICE_ROLE_KEY": self.supabase_service_role_key,
                "SUPABASE_ANON_KEY": self.supabase_anon_key,
            }.items()
            if not value
        ]
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Missing required production settings: {joined}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_runtime()
    return settings
