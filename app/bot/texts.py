from __future__ import annotations

import html

from app.bot.keyboards import ICONS
from app.models import BackgroundKind, UserSettings

_FALLBACKS = {
    "settings": "⚙️",
    "check": "✅",
    "cross": "❌",
    "pencil": "✏️",
    "attach": "📎",
    "home": "🏠",
    "eye": "👁",
    "wallet": "💰",
    "brush": "🎨",
    "media": "🖼",
    "font": "🔤",
    "format": "📐",
    "down": "⬇️",
}


def icon(name: str, *, premium: bool = True) -> str:
    fallback = _FALLBACKS[name]
    if not premium:
        return fallback
    return f'<tg-emoji emoji-id="{ICONS[name]}">{fallback}</tg-emoji>'


def main_text(settings: UserSettings, *, premium: bool = True) -> str:
    background = (
        settings.background_color
        if settings.background_kind is BackgroundKind.COLOR
        else "своё медиа"
    )
    emoji_color = settings.emoji_color or "автоматический"
    watermark = html.escape(settings.watermark_text or "выключена")
    return (
        f"{icon('settings', premium=premium)} <b>VXD3V CONVERTER</b>\n\n"
        "Создавай пиздатое оформления для ботов, каналов и сайтов.\n\n"
        f"{icon('attach', premium=premium)} <b>Отправь мне:</b>\n\n"
        "<blockquote>Отправь премиум-эмодзи, стикер или ссылку на набор.</blockquote>\n\n"
        f"{icon('settings', premium=premium)} <b>Конфигурация:</b>\n\n"
        "<blockquote>"
        f"{icon('brush', premium=premium)} Фон: {html.escape(background)}\n"
        f"{icon('format', premium=premium)} Холст: "
        f"{settings.width}×{settings.height} · {settings.fps} FPS\n"
        f"{icon('settings', premium=premium)} Размер: {settings.emoji_size_percent}%\n"
        f"{icon('brush', premium=premium)} Цвет эмодзи: {html.escape(emoji_color)}\n"
        f"{icon('font', premium=premium)} Вотермарка: {watermark}\n"
        f"{icon('media', premium=premium)} Формат: GIF в Telegram · MP4"
        "</blockquote>"
    )


def screen_text(
    title: str,
    body: str,
    *,
    icon_name: str = "settings",
    error: str | None = None,
    premium: bool = True,
) -> str:
    error_text = ""
    if error:
        error_text = f"\n\n{icon('cross', premium=premium)} {html.escape(error)}"
    return f"{icon(icon_name, premium=premium)} <b>{title}</b>\n\n{body}{error_text}"
