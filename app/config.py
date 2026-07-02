from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

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
    banner_root: Path = Path("banners")
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    rlottie_renderer_bin: str = "/usr/local/bin/tgs-renderer"
    font_file: Path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    montserrat_font_file: Path = Path("/usr/share/fonts/truetype/vxd3v/Montserrat-Regular.ttf")
    space_mono_font_file: Path = Path("/usr/share/fonts/truetype/vxd3v/SpaceMono-Regular.ttf")
    log_level: str = "INFO"
    max_input_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    max_output_bytes: int = Field(default=49 * 1024 * 1024, ge=1)
    max_render_seconds: int = Field(default=120, ge=10, le=600)
    max_concurrent_renders: int = Field(default=1, ge=1, le=8)
    max_queue_size: int = Field(default=20, ge=1, le=500)
    max_cache_bytes: int = Field(default=512 * 1024 * 1024, ge=16 * 1024 * 1024)
    enable_custom_button_emoji: bool = True
    admin_id: int | None = None
    render_price_kopecks: int = Field(default=1000, ge=100)
    min_topup_kopecks: int = Field(default=1000, ge=100)
    new_user_bonus_kopecks: int = Field(default=1000, ge=0, le=100_000)
    direct_payment_bank: str = "ВТБ"
    direct_payment_requisites: SecretStr | None = None
    direct_payment_recipient: str | None = None
    crypto_pay_token: SecretStr | None = None
    crypto_pay_api_url: str = "https://pay.crypt.bot/api"
    crypto_invoice_expires_seconds: int = Field(default=3600, ge=60, le=2_678_400)
    crypto_poll_seconds: int = Field(default=10, ge=5, le=300)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("unsupported LOG_LEVEL")
        return normalized

    @field_validator("crypto_pay_api_url")
    @classmethod
    def validate_crypto_pay_api_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme != "https" or parsed.hostname not in {
            "pay.crypt.bot",
            "testnet-pay.crypt.bot",
        }:
            raise ValueError("unsupported Crypto Pay API URL")
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
