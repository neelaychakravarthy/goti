"""Centralised env-var loader.

Single source of truth for runtime config so tests can monkeypatch
`settings.use_mocks` (and friends) instead of touching `os.environ`.
"""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Mock seam — when truthy, integrations dispatch to api/mocks/* fixtures.
    use_mocks: bool = True

    # Postgres — matches docker-compose.yml defaults.
    database_url: str = "postgresql+asyncpg://goti:goti@localhost:5432/goti"

    # Bright Data — sponsor (discovery).
    bright_data_api_key: Optional[str] = None
    bright_data_zone: Optional[str] = None
    bright_data_fb_dataset_id: Optional[str] = None

    # Other sponsor keys (read but not used in Stream C round 1; here so
    # `Settings()` doesn't choke on a real .env that includes them).
    z_ai_api_key: Optional[str] = None
    tokenrouter_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    actionbook_api_key: Optional[str] = None
    actionbook_fb_profile_id: Optional[str] = None
    actionbook_nextdoor_profile_id: Optional[str] = None
    evermind_api_key: Optional[str] = None
    nextauth_secret: Optional[str] = None


def _load_settings() -> Settings:
    """Build the singleton Settings instance.

    pydantic-settings reads `USE_MOCKS` from env by default. We want the
    `GOTI_USE_MOCKS` name from `.env.example`, so we resolve it manually
    and pass as an override.
    """
    import os

    raw = os.environ.get("GOTI_USE_MOCKS")
    overrides: dict = {}
    if raw is not None:
        overrides["use_mocks"] = raw.strip().lower() in {"1", "true", "yes", "on"}
    return Settings(**overrides)


settings = _load_settings()
