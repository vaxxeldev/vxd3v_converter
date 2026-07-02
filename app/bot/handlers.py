from __future__ import annotations

import html
import logging
import re

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, ErrorEvent, FSInputFile, Message

from app.bot.banners import BannerService
from app.bot.keyboards import (
    back_keyboard,
    background_keyboard,
    cancel_keyboard,
    emoji_color_keyboard,
    main_keyboard,
    resolution_keyboard,
    size_keyboard,
    wallet_keyboard,
    watermark_keyboard,
)
from app.bot.panel import PanelService
from app.bot.payment_handlers import process_payment_input, show_wallet_panel
from app.bot.sources import extract_sources
from app.bot.texts import icon, main_text, screen_text
from app.config import Settings
from app.models import BackgroundKind, UserSettings, WatermarkFont, WatermarkPosition
from app.repositories import PaymentRepository, SettingsRepository
from app.services.conversion import ConversionService, RenderedMedia
from app.services.crypto_pay import CryptoPaymentService
from app.services.errors import ConversionError, InsufficientBalanceError, PaymentStateError
from app.services.payments import format_rubles, parse_rubles

logger = logging.getLogger(__name__)
router = Router(name="converter")
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_ADMIN_CREDIT = re.compile(
    r"^\.пополнить\s+@([A-Za-z0-9_]{5,32})\s+([0-9]+(?:[.,][0-9]{1,2})?)$",
    re.IGNORECASE,
)
_POSITIONS = {item.value: item for item in WatermarkPosition}
_WATERMARK_FONTS = {item.value: item for item in WatermarkFont}
_POSITION_LABELS = {
    WatermarkPosition.TOP_LEFT: "сверху слева",
    WatermarkPosition.TOP_RIGHT: "сверху справа",
    WatermarkPosition.CENTER: "по центру",
    WatermarkPosition.BOTTOM_LEFT: "снизу слева",
    WatermarkPosition.BOTTOM_RIGHT: "снизу справа",
}


def _main_factory(settings: UserSettings):
    return lambda premium: (
        main_text(settings, premium=premium),
        main_keyboard(settings, premium=premium),
    )


def _screen_factory(
    title: str,
    body: str,
    keyboard_factory,
    *,
    icon_name: str = "settings",
    error: str | None = None,
):
    return lambda premium: (
        screen_text(
            title,
            body,
            icon_name=icon_name,
            error=error,
            premium=premium,
        ),
        keyboard_factory(premium),
    )


async def _show_main(
    user_id: int,
    chat_id: int,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    settings = await repository.get(user_id)
    await panel.show(user_id, chat_id, _main_factory(settings), banner="start")


@router.message(CommandStart())
async def start(
    message: Message,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    if not message.from_user:
        return
    await repository.remember_username(message.from_user.id, message.from_user.username)
    await repository.set_pending_action(message.from_user.id, None)
    await panel.delete_user_message(message)
    settings = await repository.get(message.from_user.id)
    await panel.recreate(
        message.from_user.id,
        message.chat.id,
        _main_factory(settings),
    )


@router.message(Command("cancel"))
async def cancel_command(
    message: Message,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    if not message.from_user:
        return
    await repository.set_pending_action(message.from_user.id, None)
    await panel.delete_user_message(message)
    await _show_main(message.from_user.id, message.chat.id, repository, panel)


@router.callback_query(F.data == "menu:main")
async def main_menu(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    await callback.answer()
    await repository.set_pending_action(callback.from_user.id, None)
    await _show_main(callback.from_user.id, callback.from_user.id, repository, panel)


@router.callback_query(F.data == "action:cancel")
async def cancel_input(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    await callback.answer("Ввод отменён")
    await repository.set_pending_action(callback.from_user.id, None)
    await _show_main(callback.from_user.id, callback.from_user.id, repository, panel)


@router.callback_query(F.data == "menu:wallet")
async def show_wallet(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
    app_settings: Settings,
    crypto_payments: CryptoPaymentService,
) -> None:
    await callback.answer()
    await show_wallet_panel(
        callback.from_user.id,
        repository,
        panel,
        app_settings,
    )


@router.callback_query(F.data == "menu:resolution")
async def choose_resolution(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    await callback.answer()
    await _show_resolution(callback.from_user.id, repository, panel)


async def _show_resolution(
    user_id: int,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    settings = await repository.get(user_id)
    await panel.show(
        user_id,
        user_id,
        _screen_factory(
            "РАЗРЕШЕНИЕ",
            "Выбери размер холста и частоту кадров.\n"
            f"Сейчас: <code>{settings.width}×{settings.height} · {settings.fps} FPS</code>",
            lambda premium: resolution_keyboard(settings, premium=premium),
            icon_name="format",
        ),
        banner="resolution",
    )


@router.callback_query(F.data == "menu:size")
async def choose_size(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    await callback.answer()
    await _show_size(callback.from_user.id, repository, panel)


async def _show_size(
    user_id: int,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    settings = await repository.get(user_id)
    await panel.show(
        user_id,
        user_id,
        _screen_factory(
            "РАЗМЕР ЭМОДЗИ",
            "Размер считается от меньшей стороны холста.\n"
            f"Сейчас: <code>{settings.emoji_size_percent}%</code>",
            lambda premium: size_keyboard(settings, premium=premium),
        ),
        banner="size",
    )


@router.callback_query(F.data == "menu:background")
async def choose_background(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    await callback.answer()
    await _show_background(callback.from_user.id, repository, panel)


async def _show_background(
    user_id: int,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    settings = await repository.get(user_id)
    current = (
        settings.background_color
        if settings.background_kind is BackgroundKind.COLOR
        else "загруженное медиа"
    )
    await panel.show(
        user_id,
        user_id,
        _screen_factory(
            "ФОН",
            f"Текущий фон: <code>{html.escape(current)}</code>",
            lambda premium: background_keyboard(settings, premium=premium),
            icon_name="brush",
        ),
    )


@router.callback_query(F.data == "menu:emoji_color")
async def choose_emoji_color(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    await callback.answer()
    await _show_emoji_color(callback.from_user.id, repository, panel)


async def _show_emoji_color(
    user_id: int,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    settings = await repository.get(user_id)
    current = settings.emoji_color or "автоматический контраст"
    await panel.show(
        user_id,
        user_id,
        _screen_factory(
            "ЦВЕТ ЭМОДЗИ",
            "Применяется только к перекрашиваемым эмодзи.\n"
            f"Сейчас: <code>{html.escape(current)}</code>",
            lambda premium: emoji_color_keyboard(settings, premium=premium),
            icon_name="brush",
        ),
    )


@router.callback_query(F.data == "menu:watermark")
async def choose_watermark(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    await callback.answer()
    await _show_watermark(callback.from_user.id, repository, panel)


async def _show_watermark(
    user_id: int,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    settings = await repository.get(user_id)
    text = html.escape(settings.watermark_text or "выключена")
    position = _POSITION_LABELS[settings.watermark_position]
    font = "Montserrat" if settings.watermark_font is WatermarkFont.MONTSERRAT else "Space Mono"
    await panel.show(
        user_id,
        user_id,
        _screen_factory(
            "ВОТЕРМАРКА",
            f"Текст: <code>{text}</code>\n"
            f"Шрифт: <code>{font}</code>\n"
            f"Положение: <code>{position}</code>",
            lambda premium: watermark_keyboard(settings, premium=premium),
            icon_name="font",
        ),
    )


@router.callback_query(F.data.startswith("input:"))
async def request_input(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    await callback.answer()
    action = (callback.data or "").split(":", 1)[1]
    prompts = {
        "background_color": (
            "ЦВЕТ ФОНА",
            "Отправь HEX-цвет одним сообщением.\nНапример: <code>#FFFFFF</code>",
            "brush",
        ),
        "background_media": (
            "МЕДИА-ФОН",
            "Отправь фотографию, видео или GIF.",
            "media",
        ),
        "emoji_color": (
            "ЦВЕТ ЭМОДЗИ",
            "Отправь HEX-цвет одним сообщением.\nНапример: <code>#FFFFFF</code>",
            "brush",
        ),
        "watermark": (
            "ТЕКСТ ВОТЕРМАРКИ",
            "Отправь текст длиной до 64 символов.",
            "font",
        ),
    }
    if action not in prompts:
        await _show_main(callback.from_user.id, callback.from_user.id, repository, panel)
        return
    await repository.set_pending_action(callback.from_user.id, action)
    title, body, icon_name = prompts[action]
    await panel.show(
        callback.from_user.id,
        callback.from_user.id,
        _screen_factory(
            title,
            body,
            lambda premium: cancel_keyboard(premium=premium),
            icon_name=icon_name,
        ),
    )


@router.callback_query(F.data.startswith("set:resolution:"))
async def set_resolution(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    try:
        _, _, width, height, fps = (callback.data or "").split(":")
        values = int(width), int(height), int(fps)
    except ValueError:
        await callback.answer("Некорректные параметры", show_alert=True)
        return
    allowed = {(1920, 530, 60), (1280, 720, 60), (1080, 1080, 60), (1280, 720, 30)}
    if values not in allowed:
        await callback.answer("Такого пресета нет", show_alert=True)
        return
    await repository.update(callback.from_user.id, width=values[0], height=values[1], fps=values[2])
    await callback.answer("Сохранено")
    await _show_resolution(callback.from_user.id, repository, panel)


@router.callback_query(F.data.startswith("set:size:"))
async def set_size(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    try:
        size = int((callback.data or "").rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный размер", show_alert=True)
        return
    if size not in {15, 25, 35, 50, 70, 100}:
        await callback.answer("Такого размера нет", show_alert=True)
        return
    await repository.update(callback.from_user.id, emoji_size_percent=size)
    await callback.answer("Сохранено")
    await _show_size(callback.from_user.id, repository, panel)


@router.callback_query(F.data == "set:background:color")
async def set_color_background(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    await repository.update(
        callback.from_user.id,
        background_kind=BackgroundKind.COLOR,
        background_file_id=None,
    )
    await callback.answer("Цветной фон включён")
    await _show_background(callback.from_user.id, repository, panel)


@router.callback_query(F.data == "set:emoji_color:auto")
async def set_auto_emoji_color(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    await repository.update(callback.from_user.id, emoji_color=None)
    await callback.answer("Автоматический цвет включён")
    await _show_emoji_color(callback.from_user.id, repository, panel)


@router.callback_query(F.data == "set:watermark:off")
async def disable_watermark(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    await repository.update(callback.from_user.id, watermark_text=None)
    await callback.answer("Вотермарка выключена")
    await _show_watermark(callback.from_user.id, repository, panel)


@router.callback_query(F.data.startswith("set:watermark_position:"))
async def set_watermark_position(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    value = (callback.data or "").rsplit(":", 1)[-1]
    position = _POSITIONS.get(value)
    if position is None:
        await callback.answer("Некорректная позиция", show_alert=True)
        return
    await repository.update(callback.from_user.id, watermark_position=position)
    await callback.answer("Положение сохранено")
    await _show_watermark(callback.from_user.id, repository, panel)


@router.callback_query(F.data.startswith("set:watermark_font:"))
async def set_watermark_font(
    callback: CallbackQuery,
    repository: SettingsRepository,
    panel: PanelService,
) -> None:
    font = _WATERMARK_FONTS.get((callback.data or "").rsplit(":", 1)[-1])
    if font is None:
        await callback.answer("Неизвестный шрифт", show_alert=True)
        return
    await repository.update(callback.from_user.id, watermark_font=font)
    await callback.answer("Шрифт сохранён")
    await _show_watermark(callback.from_user.id, repository, panel)


@router.callback_query(F.data == "menu:preview")
async def preview(
    callback: CallbackQuery,
    bot: Bot,
    repository: SettingsRepository,
    banner_service: BannerService,
) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    old_preview = await repository.get_preview_message(user_id)
    if old_preview:
        try:
            await bot.delete_message(user_id, old_preview)
        except TelegramBadRequest:
            pass
    media = await banner_service.resolve("preview")
    try:
        sent = await bot.send_animation(user_id, media.media)
    except TelegramBadRequest:
        if not media.cached:
            raise
        await banner_service.invalidate("preview")
        media = await banner_service.resolve("preview")
        sent = await bot.send_animation(user_id, media.media)
    if not media.cached and sent.animation:
        await banner_service.remember(media, sent.animation.file_id)
    await repository.set_preview_message(user_id, sent.message_id)


@router.message()
async def process_message(
    message: Message,
    bot: Bot,
    repository: SettingsRepository,
    payment_repository: PaymentRepository,
    conversion: ConversionService,
    panel: PanelService,
    app_settings: Settings,
    crypto_payments: CryptoPaymentService,
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    await repository.remember_username(user_id, message.from_user.username)
    command_text = (message.text or "").strip().casefold()
    if command_text.startswith(".стата"):
        await _process_admin_statistics(message, payment_repository, app_settings)
        return
    if command_text.startswith(".пополнить"):
        await _process_admin_credit(
            message,
            bot,
            repository,
            payment_repository,
            app_settings,
        )
        return
    pending = await repository.get_pending_action(user_id)
    if pending:
        if await process_payment_input(
            message,
            pending,
            bot,
            payment_repository,
            repository,
            panel,
            app_settings,
            crypto_payments,
        ):
            return
        await _process_pending(message, repository, panel, pending)
        return
    try:
        sources = await extract_sources(message, bot)
    except TelegramBadRequest:
        await panel.delete_user_message(message)
        await _show_input_error(user_id, panel, "Не удалось открыть этот набор")
        return
    if not sources:
        await panel.delete_user_message(message)
        await _show_input_error(
            user_id,
            panel,
            "Отправь премиум-эмодзи, стикер или ссылку на публичный набор",
        )
        return
    await repository.set_sources(user_id, sources)
    await panel.delete_user_message(message)
    settings = await repository.get(user_id)
    try:
        order = await payment_repository.charge_render(
            user_id,
            app_settings.render_price_kopecks,
        )
    except InsufficientBalanceError:
        await panel.show(
            user_id,
            user_id,
            _screen_factory(
                "НЕДОСТАТОЧНО СРЕДСТВ",
                "Пополните баланс, чтобы получить готовый рендер.\n"
                f"Стоимость: <code>{format_rubles(app_settings.render_price_kopecks)}</code>",
                lambda premium: wallet_keyboard(premium=premium),
                icon_name="wallet",
            ),
            banner="wallet",
        )
        return
    await _show_rendering(user_id, panel, "Рисую результат…")
    await bot.send_chat_action(user_id, ChatAction.UPLOAD_VIDEO)
    try:
        async with conversion.convert(settings, sources) as result:
            await _send_result(bot, user_id, result)
    except ConversionError as error:
        await payment_repository.refund_render(order.id)
        await _show_render_error(user_id, panel, str(error))
        return
    except BaseException:
        await payment_repository.refund_render(order.id)
        raise
    await payment_repository.complete_render(order.id)
    await _show_main(user_id, user_id, repository, panel)


async def _process_admin_statistics(
    message: Message,
    payment_repository: PaymentRepository,
    app_settings: Settings,
) -> None:
    if not message.from_user or message.from_user.id != app_settings.admin_id:
        await message.answer("Команда недоступна.")
        return
    if (message.text or "").strip().casefold() != ".стата":
        await message.answer("Формат: <code>.стата</code>")
        return
    stats = await payment_repository.statistics(message.from_user.id)
    real_topups = stats.direct_topups_kopecks + stats.crypto_topups_kopecks
    await message.answer(
        "<b>СТАТИСТИКА VXD3V</b>\n\n"
        "<b>Аудитория</b>\n"
        f"Пользователей: <code>{stats.users_total}</code>\n"
        f"Новых сегодня: <code>{stats.users_today}</code>\n"
        f"Новых за 7 дней: <code>{stats.users_seven_days}</code>\n\n"
        "<b>Рендеры</b>\n"
        f"Успешных всего: <code>{stats.renders_completed}</code>\n"
        f"Сегодня: <code>{stats.renders_today}</code>\n"
        f"За 7 дней: <code>{stats.renders_seven_days}</code>\n"
        f"С возвратом: <code>{stats.renders_refunded}</code>\n"
        f"Успешность: <code>{stats.successful_render_percent:.1f}%</code>\n"
        f"На пользователя: <code>{stats.renders_per_user:.2f}</code>\n\n"
        "<b>Финансы</b>\n"
        f"Баланс пользователей: <code>{format_rubles(stats.countable_balance_kopecks)}</code>\n"
        f"Реальные пополнения: <code>{format_rubles(real_topups)}</code>\n"
        f"Прямые переводы: <code>{format_rubles(stats.direct_topups_kopecks)}</code>\n"
        f"Crypto Bot: <code>{format_rubles(stats.crypto_topups_kopecks)}</code>\n\n"
        "<b>Ожидают обработки</b>\n"
        f"Чеков: <code>{stats.payments_awaiting_review}</code>\n"
        f"Crypto-счетов: <code>{stats.crypto_invoices_active}</code>"
    )


async def _process_admin_credit(
    message: Message,
    bot: Bot,
    repository: SettingsRepository,
    payment_repository: PaymentRepository,
    app_settings: Settings,
) -> None:
    if not message.from_user or message.from_user.id != app_settings.admin_id:
        await message.answer("Команда недоступна.")
        return
    match = _ADMIN_CREDIT.fullmatch((message.text or "").strip())
    if match is None:
        await message.answer("Формат: <code>.пополнить @username сумма</code>")
        return
    username, raw_amount = match.groups()
    try:
        amount = parse_rubles(raw_amount, 100)
    except PaymentStateError as error:
        await message.answer(html.escape(str(error)))
        return
    target_user_id = await repository.find_user_id_by_username(username)
    if target_user_id is None:
        await message.answer(
            "Пользователь не найден. Он должен сначала написать боту после обновления."
        )
        return
    balance = await payment_repository.admin_credit(target_user_id, amount)
    formatted_amount = format_rubles(amount)
    await message.answer(
        f"Баланс <b>@{html.escape(username)}</b> пополнен на "
        f"<code>{formatted_amount}</code>.\n"
        f"Текущий баланс: <code>{format_rubles(balance)}</code>."
    )
    try:
        await bot.send_message(
            target_user_id,
            f"{icon('check')} <b>Администратор пополнил ваш баланс на "
            f"{formatted_amount}</b>\n"
            f"Текущий баланс: <code>{format_rubles(balance)}</code>",
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def _process_pending(
    message: Message,
    repository: SettingsRepository,
    panel: PanelService,
    pending: str,
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    text = (message.text or "").strip()
    error: str | None = None
    destination = "main"
    if pending == "background_media":
        if message.photo:
            file_id, kind = message.photo[-1].file_id, BackgroundKind.PHOTO
        elif message.video:
            file_id, kind = message.video.file_id, BackgroundKind.VIDEO
        elif message.animation:
            file_id, kind = message.animation.file_id, BackgroundKind.ANIMATION
        else:
            error = "Нужно прислать фото, видео или GIF-анимацию"
        if error is None:
            await repository.update(
                user_id,
                background_kind=kind,
                background_file_id=file_id,
            )
            destination = "background"
    elif pending in {"background_color", "emoji_color"}:
        if not _HEX_COLOR.fullmatch(text):
            error = "Нужен HEX в формате #RRGGBB"
        elif pending == "background_color":
            await repository.update(
                user_id,
                background_kind=BackgroundKind.COLOR,
                background_color=text.upper(),
                background_file_id=None,
            )
            destination = "background"
        else:
            await repository.update(user_id, emoji_color=text.upper())
            destination = "emoji_color"
    elif pending == "watermark":
        if not text:
            error = "Текст не может быть пустым"
        elif len(text) > 64:
            error = "Вотермарка должна быть не длиннее 64 символов"
        else:
            await repository.update(user_id, watermark_text=text)
            destination = "watermark"
    else:
        await repository.set_pending_action(user_id, None)
    await panel.delete_user_message(message)
    if error:
        await _show_pending_error(user_id, panel, pending, error)
        return
    await repository.set_pending_action(user_id, None)
    if destination == "background":
        await _show_background(user_id, repository, panel)
    elif destination == "emoji_color":
        await _show_emoji_color(user_id, repository, panel)
    elif destination == "watermark":
        await _show_watermark(user_id, repository, panel)
    else:
        await _show_main(user_id, user_id, repository, panel)


async def _show_pending_error(
    user_id: int,
    panel: PanelService,
    pending: str,
    error: str,
) -> None:
    prompts = {
        "background_color": (
            "ЦВЕТ ФОНА",
            "Отправь HEX-цвет, например <code>#FFFFFF</code>",
            "brush",
        ),
        "background_media": ("МЕДИА-ФОН", "Отправь фото, видео или GIF.", "media"),
        "emoji_color": (
            "ЦВЕТ ЭМОДЗИ",
            "Отправь HEX-цвет, например <code>#FFFFFF</code>",
            "brush",
        ),
        "watermark": ("ТЕКСТ ВОТЕРМАРКИ", "Отправь текст длиной до 64 символов", "font"),
    }
    title, body, icon_name = prompts[pending]
    await panel.show(
        user_id,
        user_id,
        _screen_factory(
            title,
            body,
            lambda premium: cancel_keyboard(premium=premium),
            icon_name=icon_name,
            error=error,
        ),
    )


async def _show_input_error(user_id: int, panel: PanelService, error: str) -> None:
    await panel.show(
        user_id,
        user_id,
        _screen_factory(
            "МАТЕРИАЛ НЕ РАСПОЗНАН",
            "Поддерживаются premium emoji, стикеры и публичные ссылки на наборы.",
            lambda premium: back_keyboard(premium=premium),
            icon_name="cross",
            error=error,
        ),
    )


async def _show_rendering(user_id: int, panel: PanelService, text: str) -> None:
    await panel.show(
        user_id,
        user_id,
        _screen_factory(
            "ОБРАБОТКА",
            html.escape(text),
            lambda premium: back_keyboard(premium=premium),
            icon_name="hourglass",
        ),
        banner=None,
    )


async def _show_render_error(user_id: int, panel: PanelService, error: str) -> None:
    await panel.show(
        user_id,
        user_id,
        _screen_factory(
            "ОШИБКА ОБРАБОТКИ",
            "Не удалось собрать результат.",
            lambda premium: back_keyboard(premium=premium),
            icon_name="cross",
            error=error,
        ),
        banner=None,
    )


async def _send_result(
    bot: Bot,
    chat_id: int,
    result: RenderedMedia,
    *,
    preview: bool = False,
) -> Message:
    title = "Предпросмотр готов" if preview else "Готово"
    caption = (
        f"{icon('check')} <b>{title}</b>\n"
        f"{result.metadata.width}×{result.metadata.height} · "
        f"{result.metadata.fps:g} FPS · {result.metadata.duration_seconds:.1f} сек."
    )
    try:
        return await bot.send_animation(
            chat_id,
            FSInputFile(result.path),
            caption=caption,
            width=result.metadata.width,
            height=result.metadata.height,
        )
    except TelegramBadRequest:
        plain_caption = (
            f"✅ <b>{title}</b>\n"
            f"{result.metadata.width}×{result.metadata.height} · "
            f"{result.metadata.fps:g} FPS · {result.metadata.duration_seconds:.1f} сек."
        )
        return await bot.send_animation(
            chat_id,
            FSInputFile(result.path),
            caption=plain_caption,
            width=result.metadata.width,
            height=result.metadata.height,
        )


@router.error()
async def handle_error(event: ErrorEvent, panel: PanelService) -> bool:
    logger.exception("Unhandled Telegram update error", exc_info=event.exception)
    message = event.update.message
    if message and message.from_user:
        await _show_render_error(message.from_user.id, panel, "Внутренняя ошибка")
    return True
