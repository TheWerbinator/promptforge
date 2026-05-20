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

    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
