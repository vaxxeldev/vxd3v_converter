from __future__ import annotations

from aiogram.types import File, Sticker

from app.bot.keyboards import main_keyboard
from app.bot.sources import _from_sticker
from app.config import Settings
from app.models import StickerKind, UserSettings


def test_custom_emoji_fields_are_preserved() -> None:
    sticker = Sticker(
        file_id="main-file",
        file_unique_id="main-unique",
        type="custom_emoji",
        width=512,
        height=512,
        is_animated=True,
        is_video=False,
        emoji="✨",
        custom_emoji_id="emoji-id",
        needs_repainting=True,
        premium_animation=File(file_id="effect-file", file_unique_id="effect-unique"),
    )

    source = _from_sticker(sticker)

    assert source.kind is StickerKind.TGS
    assert source.custom_emoji_id == "emoji-id"
    assert source.needs_repainting is True
    assert source.premium_animation_file_id == "effect-file"


def test_main_keyboard_can_enable_colored_premium_buttons() -> None:
    app_settings = Settings(enable_custom_button_emoji=True)

    keyboard = main_keyboard(UserSettings(user_id=1), app_settings)
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    preview = next(button for button in buttons if button.callback_data == "menu:preview")

    assert preview.style == "primary"
    assert preview.icon_custom_emoji_id is not None
    assert preview.callback_data == "menu:preview"
    assert all(button.callback_data != "menu:format" for button in buttons)
