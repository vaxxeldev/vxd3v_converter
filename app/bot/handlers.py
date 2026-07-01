from __future__ import annotations

import html
import logging
import re

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, ErrorEvent, FSInputFile, Message

from app.bot.keyboards import (
    format_keyboard,
    main_keyboard,
    resolution_keyboard,
    size_keyboard,
)
from app.bot.sources import extract_sources
from app.config import Settings
from app.models import BackgroundKind, OutputFormat, UserSettings, WatermarkPosition
from app.repositories import SettingsRepository
from app.services.conversion import ConversionService, RenderedMedia
from app.services.errors import ConversionError

logger = logging.getLogger(__name__)
router = Router(name="converter")
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_POSITION_ALIASES = {
    "сверху слева": WatermarkPosition.TOP_LEFT,
    "сверху справа": WatermarkPosition.TOP_RIGHT,
    "по центру": WatermarkPosition.CENTER,
    "снизу слева": WatermarkPosition.BOTTOM_LEFT,
    "снизу справа": WatermarkPosition.BOTTOM_RIGHT,
}


def _welcome_text(user: UserSettings) -> str:
    return (
        "<b>Создан для пиздатого оформления ботов и сайтов</b>\n\n"
        "⬆️ <b>Отправь мне:</b>\n"
        "премиум-эмодзи (можно несколько), стикер или ссылку на emoji/sticker pack.\n\n"
        "🔣 <b>Конфигурация:</b>\n"
        f"🖌 Цвет фона: <code>{user.background_color}</code>\n"
        f"↔️ Разрешение: <code>{user.width}×{user.height} · {user.fps} FPS</code>\n"
        f"🎨 Формат: <code>{user.output_format.value}</code>\n"
        f"🔎 Размер эмодзи: <code>{user.emoji_size_percent}%</code>\n"
        f"🔤 Вотермарка: <code>{html.escape(user.watermark_text or 'выключена')}</code>"
    )


@router.message(CommandStart())
async def start(
    message: Message,
    repository: SettingsRepository,
    app_settings: Settings,
) -> None:
    if not message.from_user:
        return
    settings = await repository.get(message.from_user.id)
    await repository.set_pending_action(message.from_user.id, None)
    await message.answer(
        _welcome_text(settings),
        reply_markup=main_keyboard(settings, app_settings),
    )


@router.message(Command("cancel"))
async def cancel(message: Message, repository: SettingsRepository) -> None:
    if message.from_user:
        await repository.set_pending_action(message.from_user.id, None)
    await message.answer("Действие отменено.")


@router.callback_query(F.data == "menu:wallet")
async def show_wallet(callback: CallbackQuery, repository: SettingsRepository) -> None:
    settings = await repository.get(callback.from_user.id)
    await callback.answer(f"Баланс: {settings.balance_kopecks / 100:.2f} ₽", show_alert=True)


@router.callback_query(F.data == "menu:resolution")
async def choose_resolution(callback: CallbackQuery, app_settings: Settings) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Выбери разрешение и частоту кадров:",
            reply_markup=resolution_keyboard(app_settings),
        )


@router.callback_query(F.data == "menu:format")
async def choose_format(callback: CallbackQuery, app_settings: Settings) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Выбери способ отправки результата:",
            reply_markup=format_keyboard(app_settings),
        )


@router.callback_query(F.data == "menu:size")
async def choose_size(callback: CallbackQuery, app_settings: Settings) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Размер считается от меньшей стороны холста:",
            reply_markup=size_keyboard(app_settings),
        )


@router.callback_query(F.data == "menu:background")
async def request_background(callback: CallbackQuery, repository: SettingsRepository) -> None:
    await repository.set_pending_action(callback.from_user.id, "background_color")
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Пришли HEX-цвет, например <code>#FFFFFF</code>. /cancel — отмена."
        )


@router.callback_query(F.data == "menu:emoji_color")
async def request_emoji_color(callback: CallbackQuery, repository: SettingsRepository) -> None:
    await repository.set_pending_action(callback.from_user.id, "emoji_color")
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Пришли HEX-цвет для перекрашиваемых эмодзи или слово <code>авто</code>."
        )


@router.callback_query(F.data == "menu:watermark")
async def request_watermark(callback: CallbackQuery, repository: SettingsRepository) -> None:
    await repository.set_pending_action(callback.from_user.id, "watermark")
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Пришли <code>текст | расположение</code>. Например: "
            "<code>vxdev | снизу справа</code>. Чтобы выключить — <code>нет</code>."
        )


@router.callback_query(F.data == "menu:media")
async def request_media(callback: CallbackQuery, repository: SettingsRepository) -> None:
    await repository.set_pending_action(callback.from_user.id, "background_media")
    await callback.answer()
    if callback.message:
        await callback.message.answer("Пришли фото, видео или анимацию для фона.")


@router.callback_query(F.data == "menu:preview")
async def request_preview(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Отправь премиум-эмодзи или стикер — сразу соберу предпросмотр."
        )


@router.callback_query(F.data.startswith("set:resolution:"))
async def set_resolution(callback: CallbackQuery, repository: SettingsRepository) -> None:
    try:
        _, _, width, height, fps = (callback.data or "").split(":")
        values = int(width), int(height), int(fps)
    except ValueError:
        await callback.answer("Некорректные параметры.", show_alert=True)
        return
    allowed = {(1920, 530, 60), (1280, 720, 60), (1080, 1080, 60), (1280, 720, 30)}
    if values not in allowed:
        await callback.answer("Такого пресета нет.", show_alert=True)
        return
    await repository.update(callback.from_user.id, width=values[0], height=values[1], fps=values[2])
    await callback.answer("Разрешение сохранено.")


@router.callback_query(F.data.startswith("set:format:"))
async def set_format(callback: CallbackQuery, repository: SettingsRepository) -> None:
    try:
        output_format = OutputFormat((callback.data or "").rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный формат.", show_alert=True)
        return
    await repository.update(callback.from_user.id, output_format=output_format)
    await callback.answer("Формат сохранён.")


@router.callback_query(F.data.startswith("set:size:"))
async def set_size(callback: CallbackQuery, repository: SettingsRepository) -> None:
    try:
        size = int((callback.data or "").rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный размер.", show_alert=True)
        return
    if size not in {15, 25, 35, 50, 70, 100}:
        await callback.answer("Такого размера нет.", show_alert=True)
        return
    await repository.update(callback.from_user.id, emoji_size_percent=size)
    await callback.answer("Размер сохранён.")


@router.message()
async def process_message(
    message: Message,
    bot: Bot,
    repository: SettingsRepository,
    conversion: ConversionService,
    app_settings: Settings,
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    pending = await repository.get_pending_action(user_id)
    if pending and await _process_pending(message, repository, pending, app_settings):
        return
    try:
        sources = await extract_sources(message, bot)
    except TelegramBadRequest:
        await message.answer(
            "Не удалось открыть этот набор. Проверь ссылку или отправь сам стикер."
        )
        return
    if not sources:
        await message.answer("Отправь премиум-эмодзи, стикер или ссылку на публичный набор.")
        return
    user_settings = await repository.get(user_id)
    status = await message.answer("⏳ Рисую все кадры в 60 FPS…")
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
    try:
        async with conversion.convert(user_settings, sources) as result:
            await _send_result(message, result)
    except ConversionError as error:
        await message.answer(f"❌ {html.escape(str(error))}")
    finally:
        try:
            await status.delete()
        except TelegramBadRequest:
            pass


async def _process_pending(
    message: Message,
    repository: SettingsRepository,
    pending: str,
    app_settings: Settings,
) -> bool:
    if not message.from_user:
        return False
    user_id = message.from_user.id
    text = (message.text or "").strip()
    if pending == "background_media":
        if message.photo:
            file_id, kind = message.photo[-1].file_id, BackgroundKind.PHOTO
        elif message.video:
            file_id, kind = message.video.file_id, BackgroundKind.VIDEO
        elif message.animation:
            file_id, kind = message.animation.file_id, BackgroundKind.ANIMATION
        else:
            await message.answer("Нужно прислать фото, видео или GIF-анимацию.")
            return True
        settings = await repository.update(
            user_id,
            background_kind=kind,
            background_file_id=file_id,
        )
    elif pending in {"background_color", "emoji_color"}:
        if pending == "emoji_color" and text.lower() == "авто":
            settings = await repository.update(user_id, emoji_color=None)
        elif not _HEX_COLOR.fullmatch(text):
            await message.answer("Нужен HEX в формате <code>#RRGGBB</code>.")
            return True
        elif pending == "background_color":
            settings = await repository.update(
                user_id,
                background_kind=BackgroundKind.COLOR,
                background_color=text.upper(),
                background_file_id=None,
            )
        else:
            settings = await repository.update(user_id, emoji_color=text.upper())
    elif pending == "watermark":
        if text.lower() == "нет":
            settings = await repository.update(user_id, watermark_text=None)
        else:
            parts = [part.strip() for part in text.rsplit("|", 1)]
            if len(parts) != 2 or not parts[0] or parts[1].lower() not in _POSITION_ALIASES:
                await message.answer(
                    "Формат: <code>текст | снизу справа</code>. "
                    "Позиции: сверху/снизу слева/справа, по центру."
                )
                return True
            if len(parts[0]) > 64:
                await message.answer("Вотермарка должна быть не длиннее 64 символов.")
                return True
            settings = await repository.update(
                user_id,
                watermark_text=parts[0],
                watermark_position=_POSITION_ALIASES[parts[1].lower()],
            )
    else:
        await repository.set_pending_action(user_id, None)
        return False
    await repository.set_pending_action(user_id, None)
    await message.answer(
        "✅ Сохранено.",
        reply_markup=main_keyboard(settings, app_settings),
    )
    return True


async def _send_result(message: Message, result: RenderedMedia) -> None:
    media = FSInputFile(result.path)
    caption = (
        f"✅ {result.metadata.width}×{result.metadata.height} · "
        f"{result.metadata.fps:g} FPS · {result.metadata.duration_seconds:.1f} сек."
    )
    if result.output_format is OutputFormat.FILE:
        await message.answer_document(media, caption=caption)
    elif result.output_format is OutputFormat.VIDEO:
        await message.answer_video(
            media,
            caption=caption,
            width=result.metadata.width,
            height=result.metadata.height,
            supports_streaming=True,
        )
    else:
        await message.answer_animation(
            media,
            caption=caption,
            width=result.metadata.width,
            height=result.metadata.height,
        )


@router.error()
async def handle_error(event: ErrorEvent) -> bool:
    logger.exception("Unhandled Telegram update error", exc_info=event.exception)
    if event.update.message:
        await event.update.message.answer("❌ Внутренняя ошибка. Попробуй ещё раз чуть позже.")
    return True
