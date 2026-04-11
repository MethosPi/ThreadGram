from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTGRAM_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "AgentGram"
    environment: str = "development"
    testing: bool = False

    secret_key: str = "local-dev-secret"
    database_url: str = "sqlite+aiosqlite:///./agentgram.db"

    frontend_origin: str = "http://localhost:4173"
    public_api_base_url: str = "http://localhost:8000"
    cors_origins: list[str] = Field(default_factory=list)

    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_scope: str = "read:user user:email"

    session_cookie_name: str = "agentgram_session"
    session_https_only: bool = False
    session_same_site: str = "lax"

    auto_create_schema: bool = False

    @field_validator("frontend_origin", "public_api_base_url", mode="before")
    @classmethod
    def strip_trailing_slashes(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str] | None) -> list[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [item.rstrip("/") for item in value]
        return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]

    @property
    def effective_cors_origins(self) -> list[str]:
        origins = {self.frontend_origin.rstrip("/")}
        origins.update(self.cors_origins)
        return sorted(origins)


@lru_cache
def get_settings() -> Settings:
    return Settings()
