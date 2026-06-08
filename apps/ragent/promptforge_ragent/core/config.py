"""ragent configuration loaded from environment variables.

ragent shares the platform's Postgres (same schema, migrations owned by
apps/api) and the same HS256 JWT secret — so a token minted by apps/api is
accepted here without a round-trip back to the API. The `PF_` env prefix is
shared with apps/api on purpose: `PF_DATABASE_URL` and `PF_JWT_SECRET` are the
same secret values in both Fly apps.

`api_base_url` is ragent-specific: the agent fetches its system prompt from
apps/api at runtime, so editing the prompt in the platform changes agent
behavior on the next request (cached briefly to bound API load).
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PF_",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: SecretStr
    # Shared with apps/api so platform-issued access tokens validate here directly
    # (HS256, two services under one control — see DECISIONS).
    jwt_secret: SecretStr = Field(min_length=32)

    # Live source for the agent's system prompt. Dev points at the local API.
    api_base_url: str = "http://localhost:8000"
    # Cache the fetched system prompt this long to bound load on apps/api.
    system_prompt_cache_seconds: int = 60
    # ragent resolves its system prompt from the shared DB by natural key — the
    # demo org (by slug) + this prompt name — then fetches the BODY from apps/api
    # over HTTP with a service JWT (shared HS256 secret). No fragile id wiring:
    # apps/api's seed creates the prompt with random ids and ragent discovers it.
    # Falls back to a built-in default if the prompt isn't seeded or the fetch fails.
    demo_org_slug: str = "demo-corp"
    system_prompt_name: str = "RAG Agent System Prompt"

    # litellm model for the agent's reasoning loop.
    agent_model: str = "gpt-4o-mini"
    agent_max_iterations: int = 6

    # Upload caps (user-uploaded corpora). Bound storage + ingest/embedding cost.
    max_file_bytes: int = 5 * 1024 * 1024  # 5 MB/file
    max_corpus_bytes: int = 50 * 1024 * 1024  # 50 MB/corpus

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: list[str] = Field(default_factory=list)

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    # Cross-encoder rerank is off by default: it pulls sentence-transformers/torch
    # (the `rerank` optional extra) and a model load, which a zero-traffic demo
    # shouldn't carry. Enable + install the extra + size up the machine to use it.
    rerank_enabled: bool = False
    rerank_model: str = "BAAI/bge-reranker-base"

    def async_database_url(self) -> str:
        """Return a SQLAlchemy DSN guaranteed to use the asyncpg driver.

        Same normalizer as apps/api: cloud providers (Neon, Fly, Supabase) hand
        out bare `postgresql://` DSNs that SQLAlchemy parses as the sync psycopg2
        driver we don't ship. Rewrite the scheme and `sslmode → ssl` (asyncpg's
        param name) so any provider DSN works unedited.
        """
        raw = self.database_url.get_secret_value()
        if raw.startswith("postgresql://"):
            raw = "postgresql+asyncpg://" + raw[len("postgresql://") :]
        elif raw.startswith("postgres://"):
            raw = "postgresql+asyncpg://" + raw[len("postgres://") :]
        return raw.replace("sslmode=", "ssl=")


@lru_cache
def get_settings() -> Settings:
    return Settings()
