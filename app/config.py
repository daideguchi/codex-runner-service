from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseSettings, Field, validator


class Settings(BaseSettings):
    slack_bot_token: str = Field(..., env="SLACK_BOT_TOKEN")
    slack_channel_id: str = Field(..., env="SLACK_CHANNEL_ID")
    github_repo: str = Field(..., env="GITHUB_REPO")
    github_token: str = Field(..., env="GITHUB_TOKEN")
    state_file: Path = Field(default=Path("/var/data/codex-runner/state.json"), env="STATE_FILE")
    poll_interval_seconds: int = Field(default=120, env="POLL_INTERVAL_SECONDS")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")

    @validator("poll_interval_seconds")
    def _positive_interval(cls, value: int) -> int:
        if value < 30:
            raise ValueError("poll_interval_seconds must be >= 30 seconds to avoid rate limiting")
        return value

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.state_file.parent.mkdir(parents=True, exist_ok=True)
    return settings
