"""Configuration settings for slskd-mcp."""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from environment variables with SLSKD_ prefix."""

    model_config = SettingsConfigDict(
        env_prefix="SLSKD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    url: str = "http://127.0.0.1:5030"
    username: str = "slskd"
    password: str = "slskd"
    api_key: Optional[str] = None
    timeout: float = 30.0
    search_timeout: int = 15


# Global default settings instance
settings = Settings()
