from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import BackgroundKind, UserSettings, WatermarkPosition

ICONS = {
    "settings": "5870982283724328568",
    "check": "5870633910337015697",
    "cross": "5870657884844462243",
    "pencil": "5870676941614354370",
    "attach": "6039451237743595514",
    "home": "5873147866364514353",
    "eye": "6037397706505195857",
    "wallet": "5769126056262898415",
    "brush": "6050679691004612757",
    "media": "6035128606563241721",
    "font": "5870801517140775623",
    "format": "5778479949572738874",
    "down": "5893057118545646106",
    "hourglass": "5296482716567495148",
}


def button(
    text: str,
    callback_data: str,
    *,
    style: str | None = None,
    icon: str | None = None,
    premium: bool = True,
) -> InlineKeyboardButton:
    extra: dict[str, str] = {}
    if style:
        extra["style"] = style
    if premium and icon:
        extra["icon_custom_emoji_id"] = ICONS[icon]
    return InlineKeyboardButton(text=text, callback_data=callback_data, **extra)


def main_keyboard(settings: UserSettings, *, premium: bool = True) -> InlineKeyboardMarkup:
    balance = settings.balance_kopecks / 100
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button(f"Кошелёк · {balance:.2f} ₽", "menu:wallet", icon="wallet", premium=premium)],
            [
                button("Фон", "menu:background", icon="brush", premium=premium),
                button("Разрешение", "menu:resolution", icon="format", premium=premium),
            ],
            [
                button("Цвет эмодзи", "menu:emoji_color", icon="brush", premium=premium),
                button("Размер", "menu:size", icon="settings", premium=premium),
            ],
            [button("Вотермарка", "menu:watermark", icon="font", premium=premium)],
            [
                button(
                    "Предпросмотр",
                    "menu:preview",
                    style="primary",
                    icon="eye",
                    premium=premium,
                )
            ],
        ]
    )


def back_keyboard(*, premium: bool = True) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("Назад", "menu:main", icon="home", premium=premium)],
        ]
    )


def wallet_keyboard(*, premium: bool = True) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(
                    "Пополнить",
                    "menu:topup",
                    style="primary",
                    icon="wallet",
                    premium=premium,
                )
            ],
            [button("Назад", "menu:main", icon="home", premium=premium)],
        ]
    )


def cancel_keyboard(*, premium: bool = True) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(
                    "Отменить",
                    "action:cancel",
                    style="danger",
                    icon="cross",
                    premium=premium,
                )
            ]
        ]
    )


def resolution_keyboard(settings: UserSettings, *, premium: bool = True) -> InlineKeyboardMarkup:
    presets = [(1920, 530, 60), (1280, 720, 60), (1080, 1080, 60), (1280, 720, 30)]
    rows = []
    for width, height, fps in presets:
        selected = (width, height, fps) == (settings.width, settings.height, settings.fps)
        rows.append(
            [
                button(
                    f"{width}×{height} · {fps} FPS",
                    f"set:resolution:{width}:{height}:{fps}",
                    style="success" if selected else None,
                    icon="check" if selected else None,
                    premium=premium,
                )
            ]
        )
    rows.append([button("Назад", "menu:main", icon="home", premium=premium)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def size_keyboard(settings: UserSettings, *, premium: bool = True) -> InlineKeyboardMarkup:
    values = (15, 25, 35, 50, 70, 100)
    rows = []
    for start in range(0, len(values), 3):
        row = []
        for value in values[start : start + 3]:
            selected = value == settings.emoji_size_percent
            row.append(
                button(
                    f"{value}%",
                    f"set:size:{value}",
                    style="success" if selected else None,
                    premium=premium,
                )
            )
        rows.append(row)
    rows.append([button("Назад", "menu:main", icon="home", premium=premium)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def background_keyboard(settings: UserSettings, *, premium: bool = True) -> InlineKeyboardMarkup:
    media_selected = settings.background_kind is not BackgroundKind.COLOR
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button("Ввести HEX", "input:background_color", icon="pencil", premium=premium),
                button("Загрузить медиа", "input:background_media", icon="media", premium=premium),
            ],
            [
                button(
                    "Использовать цвет",
                    "set:background:color",
                    style="success" if media_selected else None,
                    icon="brush",
                    premium=premium,
                )
            ],
            [button("Назад", "menu:main", icon="home", premium=premium)],
        ]
    )


def emoji_color_keyboard(settings: UserSettings, *, premium: bool = True) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(
                    "Автоматический",
                    "set:emoji_color:auto",
                    style="success" if settings.emoji_color is None else None,
                    icon="check" if settings.emoji_color is None else None,
                    premium=premium,
                )
            ],
            [button("Ввести HEX", "input:emoji_color", icon="pencil", premium=premium)],
            [button("Назад", "menu:main", icon="home", premium=premium)],
        ]
    )


def watermark_keyboard(settings: UserSettings, *, premium: bool = True) -> InlineKeyboardMarkup:
    positions = [
        ("Сверху слева", WatermarkPosition.TOP_LEFT),
        ("Сверху справа", WatermarkPosition.TOP_RIGHT),
        ("По центру", WatermarkPosition.CENTER),
        ("Снизу слева", WatermarkPosition.BOTTOM_LEFT),
        ("Снизу справа", WatermarkPosition.BOTTOM_RIGHT),
    ]
    rows = [
        [button("Изменить текст", "input:watermark", icon="pencil", premium=premium)],
        [
            button(
                "Отключить",
                "set:watermark:off",
                style="danger",
                icon="cross",
                premium=premium,
            )
        ],
    ]
    for start in range(0, len(positions), 2):
        row = []
        for label, position in positions[start : start + 2]:
            selected = settings.watermark_position is position
            row.append(
                button(
                    label,
                    f"set:watermark_position:{position.value}",
                    style="success" if selected else None,
                    premium=premium,
                )
            )
        rows.append(row)
    rows.append([button("Назад", "menu:main", icon="home", premium=premium)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
