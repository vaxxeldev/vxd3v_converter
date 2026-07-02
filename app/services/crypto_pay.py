from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.config import Settings
from app.repositories.payments import CryptoInvoiceRecord, PaymentRepository
from app.services.errors import PaymentStateError
from app.services.payments import format_rubles

logger = logging.getLogger(__name__)
_PAY_URL_HOSTS = {"t.me", "telegram.me", "pay.crypt.bot", "testnet-pay.crypt.bot"}


@dataclass(slots=True, frozen=True)
class CryptoPayInvoice:
    invoice_id: int
    status: str
    pay_url: str


class CryptoPayClient:
    def __init__(self, settings: Settings) -> None:
        self._token = settings.crypto_pay_token
        self._api_url = settings.crypto_pay_api_url.rstrip("/")
        self._expires_seconds = settings.crypto_invoice_expires_seconds

    @property
    def available(self) -> bool:
        return self._token is not None

    async def create_invoice(self, user_id: int, amount_kopecks: int) -> CryptoPayInvoice:
        result = await self._request(
            "createInvoice",
            {
                "currency_type": "fiat",
                "fiat": "RUB",
                "amount": str(Decimal(amount_kopecks) / Decimal(100)),
                "description": f"Пополнение VXD3V Converter на {format_rubles(amount_kopecks)}",
                "payload": f"vxd3v:{user_id}:{amount_kopecks}",
                "allow_comments": False,
                "allow_anonymous": False,
                "expires_in": self._expires_seconds,
            },
        )
        return self._parse_invoice(result)

    async def get_invoices(self, invoice_ids: list[int]) -> list[CryptoPayInvoice]:
        if not invoice_ids:
            return []
        result = await self._request(
            "getInvoices",
            {"invoice_ids": ",".join(str(value) for value in invoice_ids), "count": 1000},
        )
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise PaymentStateError("Crypto Bot вернул некорректный список счетов.")
        return [self._parse_invoice(item) for item in result["items"]]

    async def _request(self, method: str, payload: dict[str, Any]) -> Any:
        if self._token is None:
            raise PaymentStateError("Crypto Bot временно недоступен.")
        headers = {"Crypto-Pay-API-Token": self._token.get_secret_value()}
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self._api_url}/{method}",
                    json=payload,
                    headers=headers,
                ) as response:
                    data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            raise PaymentStateError("Crypto Bot сейчас не отвечает. Попробуйте позже.") from error
        if response.status != 200 or not isinstance(data, dict) or data.get("ok") is not True:
            logger.warning("Crypto Pay request failed method=%s status=%s", method, response.status)
            raise PaymentStateError("Crypto Bot не смог создать или проверить счёт.")
        return data.get("result")

    @staticmethod
    def _parse_invoice(value: Any) -> CryptoPayInvoice:
        if not isinstance(value, dict):
            raise PaymentStateError("Crypto Bot вернул некорректный счёт.")
        try:
            invoice_id = int(value["invoice_id"])
            status = str(value["status"])
            pay_url = str(value.get("bot_invoice_url") or value.get("mini_app_invoice_url") or "")
        except (KeyError, TypeError, ValueError) as error:
            raise PaymentStateError("Crypto Bot вернул некорректный счёт.") from error
        parsed = urlparse(pay_url)
        if status not in {"active", "paid", "expired"} or (
            parsed.scheme != "https" or parsed.hostname not in _PAY_URL_HOSTS
        ):
            raise PaymentStateError("Crypto Bot вернул небезопасную ссылку на оплату.")
        return CryptoPayInvoice(invoice_id, status, pay_url)


class CryptoPaymentService:
    def __init__(self, settings: Settings, repository: PaymentRepository) -> None:
        self._settings = settings
        self._repository = repository
        self._client = CryptoPayClient(settings)

    @property
    def available(self) -> bool:
        return self._client.available

    async def create_invoice(self, user_id: int, amount_kopecks: int) -> CryptoInvoiceRecord:
        invoice = await self._client.create_invoice(user_id, amount_kopecks)
        return await self._repository.create_crypto_invoice(
            invoice.invoice_id,
            user_id,
            amount_kopecks,
            invoice.pay_url,
        )

    async def run(self, bot: Bot) -> None:
        if not self.available:
            logger.warning("Crypto Pay integration disabled: CRYPTO_PAY_TOKEN is not configured")
            return
        while True:
            try:
                await self._poll(bot)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Crypto Pay polling failed")
            await asyncio.sleep(self._settings.crypto_poll_seconds)

    async def _poll(self, bot: Bot) -> None:
        active = await self._repository.active_crypto_invoices()
        for start in range(0, len(active), 1000):
            batch = active[start : start + 1000]
            remote = await self._client.get_invoices([item.invoice_id for item in batch])
            local = {item.invoice_id: item for item in batch}
            for invoice in remote:
                if invoice.invoice_id not in local or invoice.status == "active":
                    continue
                (
                    applied,
                    user_id,
                    balance,
                    referral_reward,
                ) = await self._repository.settle_crypto_invoice(
                    invoice.invoice_id,
                    invoice.status,
                )
                if not applied or invoice.status != "paid":
                    continue
                amount = format_rubles(local[invoice.invoice_id].amount_kopecks)
                try:
                    await bot.send_message(
                        user_id,
                        f"✅ <b>Оплата через Crypto Bot получена</b>\n"
                        f"Баланс пополнен на <code>{amount}</code>.\n"
                        f"Текущий баланс: <code>{format_rubles(balance)}</code>",
                    )
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass
                if referral_reward:
                    try:
                        await bot.send_message(
                            referral_reward.referrer_user_id,
                            "💸 <b>Реферальное начисление</b>\n"
                            "На баланс зачислено "
                            f"<code>{format_rubles(referral_reward.amount_kopecks)}</code>.",
                        )
                    except (TelegramBadRequest, TelegramForbiddenError):
                        pass
