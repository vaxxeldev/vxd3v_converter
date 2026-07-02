from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import Settings
from app.models import UserSettings

_ICONS = {
    "wallet": "5769126056262898415",
    "brush": "6050679691004612757",
    "media": "6035128606563241721",
    "font": "5870801517140775623",
    "eye": "6037397706505195857",
    "settings": "5870982283724328568",
}


def _button(
    app_settings: Settings,
    text: str,
    callback_data: str,
    *,
    style: str | None = None,
    icon: str | None = None,
) -> InlineKeyboardButton:
    extra: dict[str, str] = {}
    if style:
        extra["style"] = style
    if app_settings.enable_custom_button_emoji and icon:
        extra["icon_custom_emoji_id"] = _ICONS[icon]
    return InlineKeyboardButton(text=text, callback_data=callback_data, **extra)


def main_keyboard(settings: UserSettings, app_settings: Settings) -> InlineKeyboardMarkup:
    balance = settings.balance_kopecks / 100
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(app_settings, f"Кошелёк · {balance:.2f} ₽", "menu:wallet", icon="wallet")],
            [
                _button(app_settings, "Цвет фона", "menu:background", icon="brush"),
                _button(app_settings, "Разрешение", "menu:resolution", icon="settings"),
            ],
            [
                _button(app_settings, "Своя медиа", "menu:media", icon="media"),
                _button(app_settings, "Цвет эмодзи", "menu:emoji_color", icon="brush"),
            ],
            [
                _button(app_settings, "Вотермарка", "menu:watermark", icon="font"),
                _button(app_settings, "Размер эмодзи", "menu:size", icon="settings"),
            ],
            [
                _button(
                    app_settings,
                    "Предпросмотр",
                    "menu:preview",
                    style="primary",
                    icon="eye",
                )
            ],
        ]
    )


def resolution_keyboard(app_settings: Settings) -> InlineKeyboardMarkup:
    presets = [(1920, 530, 60), (1280, 720, 60), (1080, 1080, 60), (1280, 720, 30)]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(
                    app_settings,
                    f"{width}×{height} · {fps} FPS",
                    f"set:resolution:{width}:{height}:{fps}",
                    style="primary" if index == 0 else None,
                )
            ]
            for index, (width, height, fps) in enumerate(presets)
        ]
    )


def size_keyboard(app_settings: Settings) -> InlineKeyboardMarkup:
    values = (15, 25, 35, 50, 70, 100)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(app_settings, f"{value}%", f"set:size:{value}")
                for value in values[row : row + 3]
            ]
            for row in range(0, len(values), 3)
        ]
    )
