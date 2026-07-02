from __future__ import annotations

import html
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import (
    admin_confirm_keyboard,
    back_keyboard,
    cancel_keyboard,
    crypto_invoice_keyboard,
    payment_cancel_keyboard,
    payment_methods_keyboard,
    wallet_keyboard,
)
from app.bot.panel import PanelService
from app.bot.texts import icon, screen_text
from app.config import Settings
from app.repositories import PaymentRepository, SettingsRepository
from app.repositories.payments import PaymentRequest
from app.services.crypto_pay import CryptoPaymentService
from app.services.errors import PaymentStateError
from app.services.payments import format_rubles, parse_rubles

router = Router(name="payments")
_PAYMENT_ID = re.compile(r"^[a-f0-9]{16}$")
_RECEIPT_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_RECEIPT_BYTES = 10 * 1024 * 1024


def is_admin(user_id: int, settings: Settings) -> bool:
    return settings.admin_id is not None and user_id == settings.admin_id


def _screen_factory(title: str, body: str, keyboard_factory, *, error: str | None = None):
    return lambda premium: (
        screen_text(title, body, icon_name="wallet", error=error, premium=premium),
        keyboard_factory(premium),
    )


async def show_wallet_panel(
    user_id: int,
    settings_repository: SettingsRepository,
    panel: PanelService,
    app_settings: Settings,
) -> None:
    user = await settings_repository.get(user_id)
    body = (
        f"<b>Ваш баланс:</b> <code>{format_rubles(user.balance_kopecks)}</code>\n"
        f"<b>Цена рендера:</b> "
        f"<code>{format_rubles(app_settings.render_price_kopecks)}</code>"
    )
    await panel.show(
        user_id,
        user_id,
        _screen_factory(
            "КОШЕЛЁК",
            body,
            lambda premium: wallet_keyboard(premium=premium),
        ),
        banner="wallet",
    )


@router.callback_query(F.data == "menu:topup")
async def show_topup(callback: CallbackQuery, panel: PanelService) -> None:
    await callback.answer()
    await panel.show(
        callback.from_user.id,
        callback.from_user.id,
        _screen_factory(
            "ПОПОЛНЕНИЕ БАЛАНСА",
            "Выберите удобный способ оплаты.",
            lambda premium: payment_methods_keyboard(premium=premium),
        ),
        banner="topup",
    )


@router.callback_query(F.data == "payment:direct")
async def direct_payment_amount(
    callback: CallbackQuery,
    settings_repository: SettingsRepository,
    panel: PanelService,
    app_settings: Settings,
) -> None:
    await callback.answer()
    await settings_repository.set_pending_action(callback.from_user.id, "topup_amount:direct")
    minimum = format_rubles(app_settings.min_topup_kopecks)
    await panel.show(
        callback.from_user.id,
        callback.from_user.id,
        _screen_factory(
            "ПРЯМОЙ ПЕРЕВОД",
            f"Напишите сумму пополнения.\nМинимальная сумма: <code>{minimum}</code>",
            lambda premium: cancel_keyboard(premium=premium),
        ),
        banner="topup",
    )


@router.callback_query(F.data == "payment:crypto")
async def crypto_payment_amount(
    callback: CallbackQuery,
    settings_repository: SettingsRepository,
    panel: PanelService,
    app_settings: Settings,
    crypto_payments: CryptoPaymentService,
) -> None:
    if not crypto_payments.available:
        await callback.answer("Crypto Bot временно недоступен", show_alert=True)
        return
    await callback.answer()
    await settings_repository.set_pending_action(callback.from_user.id, "topup_amount:crypto")
    minimum = format_rubles(app_settings.min_topup_kopecks)
    await panel.show(
        callback.from_user.id,
        callback.from_user.id,
        _screen_factory(
            "CRYPTO BOT",
            f"Напишите сумму пополнения в рублях.\nМинимальная сумма: <code>{minimum}</code>",
            lambda premium: cancel_keyboard(premium=premium),
        ),
        banner="topup",
    )


@router.callback_query(F.data.startswith("payment:cancel:"))
async def cancel_payment(
    callback: CallbackQuery,
    payment_repository: PaymentRepository,
    settings_repository: SettingsRepository,
    panel: PanelService,
    app_settings: Settings,
) -> None:
    payment_id = (callback.data or "").rsplit(":", 1)[-1]
    if not _PAYMENT_ID.fullmatch(payment_id):
        await callback.answer("Некорректная заявка", show_alert=True)
        return
    await payment_repository.cancel(payment_id, callback.from_user.id)
    await settings_repository.set_pending_action(callback.from_user.id, None)
    await callback.answer("Заявка отменена")
    await show_wallet_panel(callback.from_user.id, settings_repository, panel, app_settings)


async def process_payment_input(
    message: Message,
    pending: str,
    bot: Bot,
    payment_repository: PaymentRepository,
    settings_repository: SettingsRepository,
    panel: PanelService,
    app_settings: Settings,
    crypto_payments: CryptoPaymentService,
) -> bool:
    if pending in {"topup_amount", "topup_amount:direct", "topup_amount:crypto"}:
        await _process_amount(
            message,
            payment_repository,
            settings_repository,
            panel,
            app_settings,
            crypto_payments,
            "crypto" if pending.endswith(":crypto") else "direct",
        )
        return True
    if pending.startswith("payment_receipt:"):
        await _process_receipt(
            message,
            pending.rsplit(":", 1)[-1],
            bot,
            payment_repository,
            settings_repository,
            panel,
            app_settings,
        )
        return True
    return False


async def _process_amount(
    message: Message,
    payment_repository: PaymentRepository,
    settings_repository: SettingsRepository,
    panel: PanelService,
    app_settings: Settings,
    crypto_payments: CryptoPaymentService,
    method: str,
) -> None:
    if not message.from_user:
        return
    try:
        amount = parse_rubles(message.text or "", app_settings.min_topup_kopecks)
    except PaymentStateError as error:
        await panel.delete_user_message(message)
        await panel.show(
            message.from_user.id,
            message.chat.id,
            _screen_factory(
                "CRYPTO BOT" if method == "crypto" else "ПРЯМОЙ ПЕРЕВОД",
                "Напишите сумму пополнения одним сообщением.",
                lambda premium: cancel_keyboard(premium=premium),
                error=str(error),
            ),
            banner="topup",
        )
        return
    if method == "crypto":
        try:
            invoice = await crypto_payments.create_invoice(message.from_user.id, amount)
        except PaymentStateError as error:
            await panel.delete_user_message(message)
            await panel.show(
                message.from_user.id,
                message.chat.id,
                _screen_factory(
                    "CRYPTO BOT",
                    "Не удалось создать счёт. Попробуйте ещё раз.",
                    lambda premium: cancel_keyboard(premium=premium),
                    error=str(error),
                ),
                banner="topup",
            )
            return
        await settings_repository.set_pending_action(message.from_user.id, None)
        await panel.delete_user_message(message)
        await panel.show(
            message.from_user.id,
            message.chat.id,
            _screen_factory(
                "СЧЁТ CRYPTO BOT",
                f"Сумма: <code>{format_rubles(amount)}</code>\n\n"
                "После оплаты баланс пополнится автоматически.",
                lambda premium: crypto_invoice_keyboard(invoice.pay_url, premium=premium),
            ),
            banner="topup",
        )
        return
    if not app_settings.direct_payment_requisites or not app_settings.direct_payment_recipient:
        await panel.delete_user_message(message)
        await settings_repository.set_pending_action(message.from_user.id, None)
        raise PaymentStateError("Реквизиты временно недоступны.")
    payment = await payment_repository.create_direct(message.from_user.id, amount)
    await settings_repository.set_pending_action(
        message.from_user.id,
        f"payment_receipt:{payment.id}",
    )
    await panel.delete_user_message(message)
    await _show_requisites(message.from_user.id, payment, panel, app_settings)


async def _show_requisites(
    user_id: int,
    payment: PaymentRequest,
    panel: PanelService,
    app_settings: Settings,
    *,
    error: str | None = None,
) -> None:
    requisites = html.escape(app_settings.direct_payment_requisites.get_secret_value())
    recipient = html.escape(app_settings.direct_payment_recipient or "")
    bank = html.escape(app_settings.direct_payment_bank)
    body = (
        "<b>Реквизиты для оплаты</b>\n\n"
        f"<b>Банк:</b> {bank}\n"
        f"<b>Реквизиты:</b> <code>{requisites}</code>\n"
        f"<b>Получатель:</b> {recipient}\n"
        f"<b>Сумма:</b> <code>{format_rubles(payment.amount_kopecks)}</code>\n\n"
        "<b>После оплаты пришлите скриншот чека.</b>"
    )
    await panel.show(
        user_id,
        user_id,
        _screen_factory(
            "ПРЯМОЙ ПЕРЕВОД",
            body,
            lambda premium: payment_cancel_keyboard(payment.id, premium=premium),
            error=error,
        ),
        banner="topup",
    )


async def _process_receipt(
    message: Message,
    payment_id: str,
    bot: Bot,
    payment_repository: PaymentRepository,
    settings_repository: SettingsRepository,
    panel: PanelService,
    app_settings: Settings,
) -> None:
    if not message.from_user or not _PAYMENT_ID.fullmatch(payment_id):
        return
    file_id: str | None = None
    receipt_kind: str | None = None
    if message.photo:
        file_id, receipt_kind = message.photo[-1].file_id, "photo"
    elif (
        message.document
        and message.document.mime_type in _RECEIPT_MIME_TYPES
        and (message.document.file_size or 0) <= _MAX_RECEIPT_BYTES
    ):
        file_id, receipt_kind = message.document.file_id, "document"
    if not file_id or not receipt_kind:
        await panel.delete_user_message(message)
        await panel.show(
            message.from_user.id,
            message.chat.id,
            _screen_factory(
                "ЧЕК ОБ ОПЛАТЕ",
                "Пришлите скриншот как фотографию или изображение-файл до 10 МБ.",
                lambda premium: payment_cancel_keyboard(payment_id, premium=premium),
                error="Этот файл не похож на изображение чека.",
            ),
            banner="topup",
        )
        return
    payment = await payment_repository.attach_receipt(
        payment_id,
        message.from_user.id,
        file_id,
        receipt_kind,
    )
    await settings_repository.set_pending_action(message.from_user.id, None)
    await panel.delete_user_message(message)
    await _send_admin_receipt(message, payment, bot, payment_repository, app_settings)
    await panel.show(
        message.from_user.id,
        message.chat.id,
        _screen_factory(
            "ПЛАТЁЖ НА ПРОВЕРКЕ",
            "Чек отправлен администратору. После подтверждения баланс обновится автоматически.",
            lambda premium: back_keyboard(premium=premium),
        ),
        banner="topup",
    )


async def _send_admin_receipt(
    message: Message,
    payment: PaymentRequest,
    bot: Bot,
    payment_repository: PaymentRepository,
    app_settings: Settings,
) -> None:
    if app_settings.admin_id is None or payment.receipt_file_id is None:
        raise PaymentStateError("Администратор оплаты не настроен.")
    user = message.from_user
    name = html.escape(user.full_name if user else "Неизвестный пользователь")
    username = f"@{html.escape(user.username)}" if user and user.username else "нет"
    def build_caption(*, premium: bool) -> str:
        return (
        f"{icon('money', premium=premium)} <b>Новая заявка на пополнение</b>\n\n"
        f"<b>Пользователь:</b> {name}\n"
        f"<b>Username:</b> {username}\n"
        f"<b>Telegram ID:</b> <code>{payment.user_id}</code>\n"
        f"<b>Сумма:</b> <code>{format_rubles(payment.amount_kopecks)}</code>\n"
        f"<b>Заявка:</b> <code>{payment.id}</code>"
        )
    caption = build_caption(premium=True)
    keyboard = admin_confirm_keyboard(payment.id)
    try:
        if payment.receipt_kind == "photo":
            sent = await bot.send_photo(
                app_settings.admin_id,
                payment.receipt_file_id,
                caption=caption,
                reply_markup=keyboard,
            )
        else:
            sent = await bot.send_document(
                app_settings.admin_id,
                payment.receipt_file_id,
                caption=caption,
                reply_markup=keyboard,
            )
    except TelegramBadRequest:
        plain_keyboard = admin_confirm_keyboard(payment.id, premium=False)
        caption = build_caption(premium=False)
        if payment.receipt_kind == "photo":
            sent = await bot.send_photo(
                app_settings.admin_id,
                payment.receipt_file_id,
                caption=caption,
                reply_markup=plain_keyboard,
            )
        else:
            sent = await bot.send_document(
                app_settings.admin_id,
                payment.receipt_file_id,
                caption=caption,
                reply_markup=plain_keyboard,
            )
    await payment_repository.set_admin_message(payment.id, sent.message_id)


@router.callback_query(F.data.startswith("admin:approve:"))
async def approve_payment(
    callback: CallbackQuery,
    bot: Bot,
    payment_repository: PaymentRepository,
    settings_repository: SettingsRepository,
    panel: PanelService,
    app_settings: Settings,
) -> None:
    if not is_admin(callback.from_user.id, app_settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    payment_id = (callback.data or "").rsplit(":", 1)[-1]
    if not _PAYMENT_ID.fullmatch(payment_id):
        await callback.answer("Некорректная заявка", show_alert=True)
        return
    result = await payment_repository.approve(payment_id)
    if not result.applied:
        await callback.answer("Заявка уже обработана", show_alert=True)
        return
    await callback.answer("Баланс пополнен")
    if callback.message:
        caption = (callback.message.caption or "") + "\n\n✅ <b>Подтверждено</b>"
        await callback.message.edit_caption(caption=caption, reply_markup=None)
    amount = format_rubles(result.payment.amount_kopecks)
    try:
        await bot.send_message(
            result.payment.user_id,
            f"{icon('check')} <b>Баланс пополнен на {amount}</b>\n"
            f"Текущий баланс: <code>{format_rubles(result.balance_kopecks)}</code>",
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass
    await show_wallet_panel(
        result.payment.user_id,
        settings_repository,
        panel,
        app_settings,
    )
