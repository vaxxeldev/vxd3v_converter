from __future__ import annotations

import json
from urllib.parse import urlparse

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.bot.keyboards import button
from app.config import Settings
from app.repositories.broadcasts import BroadcastDraft, BroadcastJob, BroadcastRepository
from app.repositories.payments import PaymentRepository
from app.services.broadcast import BroadcastService
from app.services.payments import format_rubles

router = Router(name="admin")


def _is_admin(user_id: int, settings: Settings) -> bool:
    return settings.admin_id is not None and user_id == settings.admin_id


def admin_stats_keyboard(*, premium: bool = True) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(
                    "Рассылка",
                    "admin:broadcast",
                    style="primary",
                    icon="send_money",
                    premium=premium,
                )
            ],
            [button("Обновить", "admin:stats", icon="settings", premium=premium)],
        ]
    )


async def show_admin_statistics(
    message: Message,
    payment_repository: PaymentRepository,
    app_settings: Settings,
) -> None:
    if not message.from_user or not _is_admin(message.from_user.id, app_settings):
        await message.answer("Команда недоступна.")
        return
    text = await _admin_statistics_text(payment_repository, message.from_user.id)
    await message.answer(text, reply_markup=admin_stats_keyboard())


async def _admin_statistics_text(
    payment_repository: PaymentRepository, admin_id: int
) -> str:
    stats = await payment_repository.statistics(admin_id)
    real_topups = stats.direct_topups_kopecks + stats.crypto_topups_kopecks
    return (
        "<b>СТАТИСТИКА VXD3V</b>\n\n"
        "<b>Аудитория</b>\n"
        f"Зарегистрировано: <code>{stats.users_total}</code>\n"
        f"Доступны для рассылки: <code>{stats.users_reachable}</code>\n"
        f"Заблокировали бота: <code>{stats.users_blocked}</code>\n"
        f"Новых сегодня: <code>{stats.users_today}</code>\n"
        f"Новых за 7 дней: <code>{stats.users_seven_days}</code>\n\n"
        "<b>Рендеры</b>\n"
        f"Успешных всего: <code>{stats.renders_completed}</code>\n"
        f"Сегодня: <code>{stats.renders_today}</code>\n"
        f"За 7 дней: <code>{stats.renders_seven_days}</code>\n"
        f"С возвратом: <code>{stats.renders_refunded}</code>\n"
        f"Завершены успешно: <code>{stats.successful_render_percent:.1f}%</code>\n"
        f"Рендеров на пользователя: <code>{stats.renders_per_user:.2f}</code>\n\n"
        "<b>Финансы</b>\n"
        "Баланс без остатка ручных начислений: "
        f"<code>{format_rubles(stats.countable_balance_kopecks)}</code>\n"
        f"Реальные пополнения: <code>{format_rubles(real_topups)}</code>\n"
        f"Прямые переводы: <code>{format_rubles(stats.direct_topups_kopecks)}</code>\n"
        f"Crypto Bot: <code>{format_rubles(stats.crypto_topups_kopecks)}</code>\n\n"
        "<b>Реферальная система</b>\n"
        f"Приглашено: <code>{stats.referrals_invited}</code>\n"
        f"Активировано: <code>{stats.referrals_activated}</code>\n"
        f"Начислено: <code>{format_rubles(stats.referral_rewards_kopecks)}</code>\n\n"
        "<b>Рассылки</b>\n"
        f"Завершено: <code>{stats.broadcasts_completed}</code>\n"
        f"Доставлено: <code>{stats.broadcast_delivered}</code>\n"
        f"Блокировок: <code>{stats.broadcast_blocked}</code>\n"
        f"Ошибок: <code>{stats.broadcast_failed}</code>\n\n"
        "<b>Ожидают обработки</b>\n"
        f"Чеков: <code>{stats.payments_awaiting_review}</code>\n"
        f"Crypto-счетов: <code>{stats.crypto_invoices_active}</code>"
    )


@router.callback_query(F.data == "admin:stats")
async def refresh_admin_statistics(
    callback: CallbackQuery,
    payment_repository: PaymentRepository,
    app_settings: Settings,
) -> None:
    if not _is_admin(callback.from_user.id, app_settings) or not callback.message:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.answer()
    text = await _admin_statistics_text(payment_repository, callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=admin_stats_keyboard())
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error).casefold():
            raise


@router.callback_query(F.data == "admin:broadcast")
async def begin_broadcast(
    callback: CallbackQuery,
    broadcast_repository: BroadcastRepository,
    app_settings: Settings,
) -> None:
    if not _is_admin(callback.from_user.id, app_settings) or not callback.message:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    if await broadcast_repository.active_job():
        await callback.answer("Рассылка уже выполняется", show_alert=True)
        return
    await callback.message.edit_text(
        "📨 <b>Шаг 1: отправьте текст рассылки</b>\n\n"
        "Форматирование и premium emoji сохранятся.",
        reply_markup=_cancel_keyboard(),
    )
    await broadcast_repository.start_draft(
        callback.from_user.id,
        callback.message.chat.id,
        callback.message.message_id,
    )
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast:cancel")
async def cancel_broadcast(
    callback: CallbackQuery,
    broadcast_repository: BroadcastRepository,
    app_settings: Settings,
) -> None:
    if not _is_admin(callback.from_user.id, app_settings) or not callback.message:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    draft = await broadcast_repository.draft(callback.from_user.id)
    if draft and draft.preview_message_id:
        try:
            await callback.bot.delete_message(callback.message.chat.id, draft.preview_message_id)
        except TelegramBadRequest:
            pass
    await broadcast_repository.delete_draft(callback.from_user.id)
    await callback.message.edit_text(
        "Рассылка отменена.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[button("Назад", "admin:stats", icon="home")]]
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast:skip_media")
async def skip_media(
    callback: CallbackQuery,
    broadcast_repository: BroadcastRepository,
    app_settings: Settings,
) -> None:
    if not _is_admin(callback.from_user.id, app_settings) or not callback.message:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    draft = await broadcast_repository.draft(callback.from_user.id)
    if draft is None or draft.state != "media":
        await callback.answer("Черновик устарел", show_alert=True)
        return
    await broadcast_repository.update_draft(
        callback.from_user.id, state="button", media_type=None, media_file_id=None
    )
    await _ask_button(callback.message)
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast:add_button")
async def add_button(
    callback: CallbackQuery,
    broadcast_repository: BroadcastRepository,
    app_settings: Settings,
) -> None:
    if not _is_admin(callback.from_user.id, app_settings) or not callback.message:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    draft = await broadcast_repository.draft(callback.from_user.id)
    if draft is None or draft.state != "button":
        await callback.answer("Черновик устарел", show_alert=True)
        return
    await broadcast_repository.update_draft(callback.from_user.id, state="button_text")
    await callback.message.edit_text(
        "🔗 <b>Шаг 3: отправьте текст кнопки</b>\n\n"
        "Можно добавить один premium emoji.",
        reply_markup=_cancel_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast:skip_button")
async def skip_button(
    callback: CallbackQuery,
    broadcast_repository: BroadcastRepository,
    app_settings: Settings,
) -> None:
    if not _is_admin(callback.from_user.id, app_settings) or not callback.message:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    draft = await broadcast_repository.draft(callback.from_user.id)
    if draft is None or draft.state != "button":
        await callback.answer("Черновик устарел", show_alert=True)
        return
    await broadcast_repository.update_draft(
        callback.from_user.id,
        state="preview",
        button_text=None,
        button_url=None,
        button_emoji_id=None,
    )
    await _show_preview(callback.bot, callback.message, broadcast_repository, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast:confirm")
async def confirm_broadcast(
    callback: CallbackQuery,
    broadcast_repository: BroadcastRepository,
    app_settings: Settings,
) -> None:
    if not _is_admin(callback.from_user.id, app_settings) or not callback.message:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    draft = await broadcast_repository.draft(callback.from_user.id)
    if draft is None or draft.state != "preview":
        await callback.answer("Черновик уже обработан", show_alert=True)
        return
    if draft.preview_message_id:
        try:
            await callback.bot.delete_message(callback.message.chat.id, draft.preview_message_id)
        except TelegramBadRequest:
            pass
    await callback.message.edit_text("📤 <b>Рассылка запускается…</b>")
    try:
        job = await broadcast_repository.create_job(
            callback.from_user.id,
            callback.message.chat.id,
            callback.message.message_id,
        )
    except RuntimeError:
        await callback.answer("Рассылка уже запущена", show_alert=True)
        return
    await callback.message.edit_text(
        f"📤 <b>Рассылка начата</b>\n\nПолучателей: <code>{job.total}</code>"
    )
    await callback.answer()


async def process_broadcast_input(
    message: Message,
    bot: Bot,
    repository: BroadcastRepository,
    settings: Settings,
) -> bool:
    if not message.from_user or not _is_admin(message.from_user.id, settings):
        return False
    draft = await repository.draft(message.from_user.id)
    if draft is None:
        return False
    if draft.state == "text":
        text = message.text or message.caption
        entities = message.entities or message.caption_entities
        if not text or _telegram_length(text) > 1024:
            await message.answer("Текст должен содержать от 1 до 1024 символов.")
            return True
        entities_json = json.dumps(
            [entity.model_dump(mode="json", exclude_none=True) for entity in entities or []],
            ensure_ascii=False,
        )
        await repository.update_draft(
            message.from_user.id,
            state="media",
            text=text,
            entities_json=entities_json,
        )
        await _delete_input(message)
        await _edit_control(
            bot,
            draft,
            "🖼 <b>Шаг 2: отправьте фото, видео или GIF</b>\n\n"
            "Либо нажмите «Пропустить».",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [button("Пропустить", "admin:broadcast:skip_media", icon="check")],
                    [button("Отмена", "admin:broadcast:cancel", style="danger", icon="cross")],
                ]
            ),
        )
        return True
    if draft.state == "media":
        media_type = None
        file_id = None
        if message.photo:
            media_type, file_id = "photo", message.photo[-1].file_id
        elif message.video:
            media_type, file_id = "video", message.video.file_id
        elif message.animation:
            media_type, file_id = "animation", message.animation.file_id
        if not media_type or not file_id:
            await message.answer("Отправьте фото, видео, GIF или нажмите «Пропустить».")
            return True
        await repository.update_draft(
            message.from_user.id,
            state="button",
            media_type=media_type,
            media_file_id=file_id,
        )
        await _delete_input(message)
        await _edit_control(bot, draft, "🔗 <b>Добавить кнопку со ссылкой?</b>", _button_keyboard())
        return True
    if draft.state == "button_text":
        text = (message.text or "").strip()
        emoji_id = None
        for entity in message.entities or []:
            if entity.type == "custom_emoji" and entity.custom_emoji_id:
                emoji = entity.extract_from(message.text or "")
                emoji_id = entity.custom_emoji_id
                text = text.replace(emoji, "", 1).strip()
                break
        if not text and not emoji_id:
            await message.answer("Текст кнопки не может быть пустым.")
            return True
        if _telegram_length(text) > 64:
            await message.answer("Текст кнопки должен быть не длиннее 64 символов.")
            return True
        await repository.update_draft(
            message.from_user.id,
            state="button_url",
            button_text=text,
            button_emoji_id=emoji_id,
        )
        await _delete_input(message)
        await _edit_control(
            bot,
            draft,
            "🔗 <b>Шаг 4: отправьте HTTPS-ссылку для кнопки</b>",
            _cancel_keyboard(),
        )
        return True
    if draft.state == "button_url":
        url = (message.text or "").strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or len(url) > 2048:
            await message.answer("Нужна корректная HTTPS-ссылка.")
            return True
        await repository.update_draft(message.from_user.id, state="preview", button_url=url)
        await _delete_input(message)
        current = await repository.draft(message.from_user.id)
        if current:
            await _show_preview_from_draft(bot, current, repository)
        return True
    await message.answer("Завершите или отмените текущую рассылку.")
    return True


async def _show_preview(
    bot: Bot, message: Message, repository: BroadcastRepository, admin_id: int
) -> None:
    draft = await repository.draft(admin_id)
    if draft:
        await _show_preview_from_draft(bot, draft, repository)


async def _show_preview_from_draft(
    bot: Bot, draft: BroadcastDraft, repository: BroadcastRepository
) -> None:
    job = BroadcastJob(
        "preview",
        draft.admin_id,
        draft.text,
        draft.entities_json,
        draft.media_type,
        draft.media_file_id,
        draft.button_text,
        draft.button_url,
        draft.button_emoji_id,
        "preview",
        1,
        0,
        0,
        0,
        None,
        None,
    )
    preview = await BroadcastService.send_payload(bot, draft.admin_id, job)
    await repository.update_draft(
        draft.admin_id, state="preview", preview_message_id=preview.message_id
    )
    await _edit_control(
        bot,
        draft,
        "👁 <b>Предпросмотр готов. Отправить рассылку?</b>",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    button(
                        "Отправить",
                        "admin:broadcast:confirm",
                        style="success",
                        icon="check",
                    ),
                    button(
                        "Отмена",
                        "admin:broadcast:cancel",
                        style="danger",
                        icon="cross",
                    ),
                ]
            ]
        ),
    )


async def _ask_button(message: Message) -> None:
    await message.edit_text(
        "🔗 <b>Добавить кнопку со ссылкой?</b>", reply_markup=_button_keyboard()
    )


def _button_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("Добавить кнопку", "admin:broadcast:add_button", icon="attach")],
            [button("Без кнопки", "admin:broadcast:skip_button", icon="check")],
            [button("Отмена", "admin:broadcast:cancel", style="danger", icon="cross")],
        ]
    )


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("Отмена", "admin:broadcast:cancel", style="danger", icon="cross")]
        ]
    )


async def _delete_input(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


async def _edit_control(
    bot: Bot,
    draft: BroadcastDraft,
    text: str,
    markup: InlineKeyboardMarkup,
) -> None:
    if draft.control_chat_id is None or draft.control_message_id is None:
        return
    await bot.edit_message_text(
        text,
        chat_id=draft.control_chat_id,
        message_id=draft.control_message_id,
        reply_markup=markup,
    )


def _telegram_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2
