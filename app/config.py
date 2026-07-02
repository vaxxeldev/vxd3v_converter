from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "API_TOKEN")
    )
    database_path: Path = Path("/app/data/bot.sqlite3")
    temp_root: Path = Path(tempfile.gettempdir()) / "vxd3v-converter"
    cache_root: Path = Path("/app/data/cache")
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    rlottie_renderer_bin: str = "/usr/local/bin/tgs-renderer"
    font_file: Path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    log_level: str = "INFO"
    max_input_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    max_output_bytes: int = Field(default=49 * 1024 * 1024, ge=1)
    max_render_seconds: int = Field(default=120, ge=10, le=600)
    max_concurrent_renders: int = Field(default=1, ge=1, le=8)
    max_queue_size: int = Field(default=20, ge=1, le=500)
    max_cache_bytes: int = Field(default=512 * 1024 * 1024, ge=16 * 1024 * 1024)
    enable_custom_button_emoji: bool = True

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("unsupported LOG_LEVEL")
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
