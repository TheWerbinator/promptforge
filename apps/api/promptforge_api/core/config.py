"""Application configuration loaded from environment variables.

Uses pydantic-settings directly. Validation runs at app import time; misconfigured
deploys fail before accepting traffic.
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
    jwt_secret: SecretStr = Field(min_length=32)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: list[str] = Field(default_factory=list)

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    queue_poll_interval_ms: int = 250
    queue_worker_concurrency: int = 4

    demo_email: str = "demo@promptforge.dev"
    demo_rate_limit: str = "5/minute"
    # Free real LLM runs a demo visitor gets on the hosted key (per client IP per
    # day) before they must supply their own provider key. Gives a genuine taste
    # without letting one visitor — or a bot — run up the hosted-key bill.
    demo_free_runs: int = 5

    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    # Refresh-token reaper: hard-delete tokens whose expires_at is older than the
    # retention window. The worker runs it on this interval.
    refresh_retention_days: int = 90
    refresh_reaper_interval_hours: int = 24

    # When False, the refresh cookie is set without Secure (required for HTTP
    # local dev and the in-process TestClient). Always True in deployed envs.
    cookie_secure: bool = True

    def async_database_url(self) -> str:
        """Return a SQLAlchemy DSN guaranteed to use the asyncpg driver.

        Cloud providers (Neon, Fly Postgres, Supabase) hand out DSNs with the
        bare `postgresql://` scheme. SQLAlchemy parses that as psycopg2-default,
        which is the sync driver we deliberately don't ship. Rewrite the scheme
        and the sslmode → ssl query param (asyncpg's naming) so any of the
        common provider DSN shapes works without manual editing.
        """
        raw = self.database_url.get_secret_value()
        if raw.startswith("postgresql://"):
            raw = "postgresql+asyncpg://" + raw[len("postgresql://") :]
        elif raw.startswith("postgres://"):
            raw = "postgresql+asyncpg://" + raw[len("postgres://") :]
        # asyncpg uses `ssl=` not `sslmode=`. SQLAlchemy's asyncpg dialect
        # translates this in recent versions, but normalizing makes it
        # provider-agnostic and survives future SQLAlchemy changes.
        return raw.replace("sslmode=", "ssl=")


@lru_cache
def get_settings() -> Settings:
    return Settings()
