"""Settings loader for the Goti FastAPI backend.

All runtime configuration comes from environment variables (loaded from a
project-root `.env` file in dev via pydantic-settings). The `GOTI_USE_MOCKS`
flag is plumbed for Stream C's mocks-mode and is currently unused.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database (Postgres on Zeabur in prod; docker-compose service `postgres` in dev)
    database_url: str = Field(
        default="postgresql+asyncpg://goti:goti@postgres:5432/goti",
        alias="DATABASE_URL",
    )

    # LLM gateway — every model call goes through TokenRouter (SPEC.md "Tech stack / AI")
    tokenrouter_api_key: str | None = Field(default=None, alias="TOKENROUTER_API_KEY")
    tokenrouter_base_url: str = Field(
        default="https://api.tokenrouter.io/v1",
        alias="TOKENROUTER_BASE_URL",
    )
    # The TokenRouter routing string that resolves to Z.AI GLM-5.1. Per Pass-1
    # research: TokenRouter is OpenAI-compatible and likely accepts the
    # OpenRouter-namespace convention `z-ai/glm-5.1`. Override via env var if
    # the live identifier differs.
    glm_model_id: str = Field(default="z-ai/glm-5.1", alias="GLM_MODEL_ID")

    # Memory store
    everos_api_key: str | None = Field(default=None, alias="EVEROS_API_KEY")

    # Actionbook MCP + OAuth (Stream B owns MCP client + OAuth; Stream C owns
    # marketplace-verb wrappers on top). Clerk is the OAuth issuer fronting
    # the Actionbook MCP server. Dynamic Client Registration (RFC 7591) means
    # we register Goti's client_id on first link request — no pre-arranged
    # client credentials needed. Override via ACTIONBOOK_OAUTH_REGISTERED_CLIENT_ID
    # if a deployment wants stable credentials across container restarts.
    actionbook_mcp_url: str = Field(
        default="https://edge.actionbook.dev/mcp",
        alias="ACTIONBOOK_MCP_URL",
    )
    actionbook_oauth_issuer: str = Field(
        default="https://clerk.actionbook.dev",
        alias="ACTIONBOOK_OAUTH_ISSUER",
    )
    actionbook_oauth_redirect_uri: str = Field(
        default="http://localhost:8000/api/integrations/{provider}/oauth/callback",
        alias="ACTIONBOOK_OAUTH_REDIRECT_URI",
    )
    actionbook_oauth_registered_client_id: str | None = Field(
        default=None, alias="ACTIONBOOK_OAUTH_REGISTERED_CLIENT_ID"
    )

    # AgentField control plane (docker-compose service `af-server`)
    af_control_plane_url: str = Field(
        default="http://af-server:8080",
        alias="AF_CONTROL_PLANE_URL",
    )

    # Stream C's mock-externals gate. Scaffolded only — unused this increment.
    use_mocks: bool = Field(default=False, alias="GOTI_USE_MOCKS")

    # Single demo user — see SPEC.md "Auth"
    demo_user_id: str = Field(default="demo_user", alias="GOTI_DEMO_USER_ID")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
