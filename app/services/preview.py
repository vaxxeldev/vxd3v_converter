from __future__ import annotations

from dataclasses import replace

from app.models import UserSettings, WatermarkPosition


def preview_settings(settings: UserSettings) -> UserSettings:
    return replace(
        settings,
        watermark_text="предпросмотр",
        watermark_position=WatermarkPosition.CENTER,
        watermark_font_scale=0.20,
    )
