"""Settings loader for the Goti FastAPI backend.

All runtime configuration comes from environment variables (loaded from a
project-root `.env` file in dev via pydantic-settings).
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _ensure_asyncpg_scheme(uri: str) -> str:
    """Rewrite a Postgres URI to use the asyncpg driver scheme.

    Zeabur's Postgres add-on auto-injects ``POSTGRES_URI`` as a standard
    ``postgresql://...`` URL (the sync driver scheme). SQLAlchemy's
    ``create_async_engine`` requires the explicit ``+asyncpg`` suffix,
    otherwise it tries to load psycopg2 and crashes. Rewrite the prefix
    so both Zeabur's native shape and a developer-supplied
    ``postgresql+asyncpg://...`` work without modification.
    """
    if uri.startswith("postgresql+asyncpg://"):
        return uri
    if uri.startswith("postgresql://"):
        return "postgresql+asyncpg://" + uri[len("postgresql://") :]
    if uri.startswith("postgres://"):
        return "postgresql+asyncpg://" + uri[len("postgres://") :]
    # SQLite (test mode) + anything else pass through unchanged.
    return uri


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Postgres connection string. The env var is ``POSTGRES_URI`` — the
    # name Zeabur's Postgres add-on auto-injects into linked services
    # (see ZEABUR.md). Same var name is used in dev (docker-compose +
    # .env) so there's a single canonical name across environments.
    #
    # We accept both the asyncpg-scheme form (``postgresql+asyncpg://``)
    # and the standard sync form (``postgresql://`` / ``postgres://``)
    # — a ``field_validator`` below rewrites the prefix so SQLAlchemy's
    # async engine always gets the driver it needs.
    #
    # Default points at docker-compose's ``postgres`` service hostname.
    # On Zeabur that name does not resolve (``gaierror: Name or service
    # not known``); ``POSTGRES_URI`` must be set there.
    database_url: str = Field(
        default="postgresql+asyncpg://goti:goti@postgres:5432/goti",
        alias="POSTGRES_URI",
    )

    @field_validator("database_url", mode="after")
    @classmethod
    def _coerce_async_driver(cls, v: str) -> str:
        return _ensure_asyncpg_scheme(v)

    # LLM — Anthropic Claude. Two model knobs:
    #
    # - ``CLAUDE_MODEL_ID`` (default Haiku 4.5) — fast + cheap, used by the
    #   reasoners in ``api/llm.py`` (clarifier / valuation / negotiation
    #   drafter). These calls return short JSON or plain text; Haiku is
    #   plenty.
    # - ``CLAUDE_BROWSER_MODEL_ID`` (default Sonnet 4.6) — used by
    #   ``browser_use.Agent`` for the per-step browse loop. The
    #   AgentOutput schema is large (thinking + memory + next_goal +
    #   list[action]) and Haiku drops the required ``action`` field
    #   under tool-call pressure; Sonnet handles it reliably.
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    claude_model_id: str = Field(
        default="claude-haiku-4-5-20251001",
        alias="CLAUDE_MODEL_ID",
    )
    claude_browser_model_id: str = Field(
        default="claude-sonnet-4-6",
        alias="CLAUDE_BROWSER_MODEL_ID",
    )

    # Memory store
    everos_api_key: str | None = Field(default=None, alias="EVEROS_API_KEY")

    # Browserbase — Goti owns a single API key + a single project id
    # (https://browserbase.com/dashboard). Each Goti user gets one
    # Browserbase Context (``bb_ctx_*``) that persists their FB
    # Marketplace + Nextdoor cookies across sessions. Initial login
    # happens in a kept-alive Browserbase session opened in a new
    # browser tab via the Live View URL; backend automation
    # (send_message / fetch_replies) mints fresh sessions bound to the
    # same context so cookies persist back.
    browserbase_api_key: str | None = Field(
        default=None, alias="BROWSERBASE_API_KEY"
    )
    browserbase_project_id: str | None = Field(
        default=None, alias="BROWSERBASE_PROJECT_ID"
    )
    # Hard cap on concurrent Browserbase sessions Goti will mint. Bound
    # by Browserbase's per-project concurrent-browsers quota — free
    # tier = 3, Developer = 25, Startup = 100. Goti enforces this with
    # an in-process semaphore so discovery iterations + parallel
    # negotiation jobs never exceed the quota and trigger HTTP 410s on
    # the older sessions. The default leaves one permit unused so a
    # Live View login session (minted outside the semaphore) doesn't
    # push us over the upstream quota.
    browserbase_max_concurrent: int = Field(
        default=24, alias="BROWSERBASE_MAX_CONCURRENT"
    )

    # AgentField has TWO related URLs, and confusing them causes the agent
    # server to be unreachable. Read both docstrings carefully.
    #
    # ``af_control_plane_url`` — **FastAPI itself is the control plane.** The
    # bridge router in ``api/routes/agent_bridge.py`` mounts the
    # ``/api/v1/...`` endpoints the AgentField SDK speaks to (request-approval,
    # heartbeats, agent registration, memory-events WS). The default points
    # at uvicorn's port so the agent server (which runs in the same container
    # / pod) can reach FastAPI via loopback. Used for AgentField SDK outbound
    # calls FROM the agent server TO FastAPI.
    #
    # Do NOT point this at the agent's own port (8080) — that would be
    # circular: agent → "control plane" → back to agent.
    af_control_plane_url: str = Field(
        default="http://localhost:8000",
        alias="AF_CONTROL_PLANE_URL",
    )

    # ``af_agent_server_url`` — **The AgentField agent server.** Reasoners
    # registered via ``@app.reasoner()`` are served at
    # ``{af_agent_server_url}/api/v1/execute/{node_id}.{method}``. FastAPI
    # (and the rest of the orchestration layer in ``api/orchestration/``)
    # invokes reasoners by POSTing to these URLs. The agent server runs on
    # port 8080 in the same container/pod as FastAPI; see ``docker-compose.yml``
    # for the dual-process command line.
    af_agent_server_url: str = Field(
        default="http://localhost:8080",
        alias="AF_AGENT_SERVER_URL",
    )

    # CORS — comma-separated list of allowed origins for the deployed
    # frontend(s). Empty default falls back to permissive local-dev
    # origins (see api/main.py). Set this to your Vercel deployment URL
    # in production.
    allowed_origins: str = Field(default="", alias="GOTI_ALLOWED_ORIGINS")

    # Google OAuth. The frontend's NextAuth Google provider signs
    # in the user with this client_id; the backend verifies ID tokens
    # against the same audience via Google's JWKS. Both ends MUST share
    # the same client_id for token verification to succeed.
    google_oauth_client_id: str | None = Field(
        default=None, alias="GOOGLE_OAUTH_CLIENT_ID"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
