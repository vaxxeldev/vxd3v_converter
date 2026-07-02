from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from app.bot.payment_handlers import is_admin
from app.config import Settings
from app.models import UserSettings, WatermarkFont, WatermarkPosition
from app.repositories import PaymentRepository, SettingsRepository
from app.repositories.payments import PaymentStatus
from app.services.crypto_pay import CryptoPayClient
from app.services.errors import InsufficientBalanceError, PaymentStateError
from app.services.payments import format_rubles, parse_rubles
from app.services.preview import preview_settings


async def _repositories(tmp_path: Path) -> tuple[SettingsRepository, PaymentRepository]:
    database = tmp_path / "bot.sqlite3"
    settings = SettingsRepository(database)
    await settings.initialize()
    payments = PaymentRepository(database)
    await payments.initialize()
    return settings, payments


@pytest.mark.parametrize(
    ("value", "expected"),
    [("10", 1000), ("100.50", 10050), ("25,5", 2550)],
)
def test_parse_rubles_without_float_rounding(value: str, expected: int) -> None:
    assert parse_rubles(value, 1000) == expected


@pytest.mark.parametrize("value", ["9.99", "-10", "10.999", "text", ""])
def test_parse_rubles_rejects_invalid_or_small_values(value: str) -> None:
    with pytest.raises(PaymentStateError):
        parse_rubles(value, 1000)


def test_format_rubles() -> None:
    assert format_rubles(1000) == "10 ₽"
    assert format_rubles(10050) == "100.50 ₽"


def test_crypto_invoice_parser_accepts_only_trusted_payment_links() -> None:
    valid = CryptoPayClient._parse_invoice(
        {
            "invoice_id": 123,
            "status": "active",
            "bot_invoice_url": "https://t.me/CryptoBot?start=invoice-123",
        }
    )
    assert valid.invoice_id == 123

    with pytest.raises(PaymentStateError):
        CryptoPayClient._parse_invoice(
            {
                "invoice_id": 124,
                "status": "active",
                "bot_invoice_url": "https://example.com/fake-invoice",
            }
        )


async def test_direct_payment_is_credited_exactly_once(tmp_path: Path) -> None:
    settings, payments = await _repositories(tmp_path)
    await settings.get(10)
    request = await payments.create_direct(10, 2500)
    review = await payments.attach_receipt(request.id, 10, "receipt-file", "photo")

    first = await payments.approve(request.id)
    second = await payments.approve(request.id)

    assert review.status is PaymentStatus.AWAITING_REVIEW
    assert first.applied is True
    assert first.balance_kopecks == 2500
    assert second.applied is False
    assert second.balance_kopecks == 2500
    assert (await settings.get(10)).balance_kopecks == 2500


async def test_canceled_payment_cannot_accept_receipt(tmp_path: Path) -> None:
    settings, payments = await _repositories(tmp_path)
    await settings.get(10)
    request = await payments.create_direct(10, 1000)

    assert await payments.cancel(request.id, 10) is True
    with pytest.raises(PaymentStateError):
        await payments.attach_receipt(request.id, 10, "receipt", "photo")


async def test_render_charge_and_refund_are_atomic_and_idempotent(tmp_path: Path) -> None:
    settings, payments = await _repositories(tmp_path)
    await settings.get(20)
    async with aiosqlite.connect(tmp_path / "bot.sqlite3") as connection:
        await connection.execute(
            "UPDATE user_settings SET balance_kopecks = 1000 WHERE user_id = 20"
        )
        await connection.commit()

    order = await payments.charge_render(20, 1000)
    assert (await settings.get(20)).balance_kopecks == 0
    assert await payments.refund_render(order.id) is True
    assert await payments.refund_render(order.id) is False
    assert (await settings.get(20)).balance_kopecks == 1000


async def test_render_requires_sufficient_balance(tmp_path: Path) -> None:
    settings, payments = await _repositories(tmp_path)
    await settings.get(30)

    with pytest.raises(InsufficientBalanceError):
        await payments.charge_render(30, 1000)


async def test_interrupted_render_is_refunded_on_startup(tmp_path: Path) -> None:
    settings, payments = await _repositories(tmp_path)
    await settings.get(40)
    async with aiosqlite.connect(tmp_path / "bot.sqlite3") as connection:
        await connection.execute(
            "UPDATE user_settings SET balance_kopecks = 1000 WHERE user_id = 40"
        )
        await connection.commit()
    await payments.charge_render(40, 1000)

    assert await payments.refund_interrupted_renders() == 1
    assert (await settings.get(40)).balance_kopecks == 1000


def test_only_configured_admin_is_authorized() -> None:
    settings = Settings(admin_id=2009632768)

    assert is_admin(2009632768, settings) is True
    assert is_admin(123, settings) is False


def test_preview_forces_large_centered_preview_watermark() -> None:
    source = UserSettings(
        user_id=1,
        watermark_text="custom",
        watermark_position=WatermarkPosition.TOP_LEFT,
    )

    preview = preview_settings(source)

    assert preview.watermark_text == "предпросмотр"
    assert preview.watermark_position is WatermarkPosition.CENTER
    assert preview.watermark_font_scale == 0.20
    assert preview.watermark_font is WatermarkFont.MONTSERRAT
    assert source.watermark_text == "custom"


async def test_admin_credit_updates_balance_and_ledger(tmp_path: Path) -> None:
    settings, payments = await _repositories(tmp_path)
    await settings.get(50)

    balance = await payments.admin_credit(50, 1250)

    assert balance == 1250
    assert (await settings.get(50)).balance_kopecks == 1250
    async with aiosqlite.connect(tmp_path / "bot.sqlite3") as connection:
        cursor = await connection.execute(
            "SELECT amount_kopecks FROM balance_transactions "
            "WHERE user_id = 50 AND kind = 'admin_credit'"
        )
        assert await cursor.fetchone() == (1250,)


async def test_username_is_normalized_and_reassigned(tmp_path: Path) -> None:
    settings, _ = await _repositories(tmp_path)
    await settings.remember_username(60, "Some_User")
    assert await settings.find_user_id_by_username("@some_user") == 60

    await settings.remember_username(61, "SOME_USER")

    assert await settings.find_user_id_by_username("some_user") == 61


async def test_crypto_invoice_is_credited_exactly_once(tmp_path: Path) -> None:
    settings, payments = await _repositories(tmp_path)
    await settings.get(70)
    await payments.create_crypto_invoice(777, 70, 2500, "https://t.me/CryptoBot?start=invoice")

    first = await payments.settle_crypto_invoice(777, "paid")
    second = await payments.settle_crypto_invoice(777, "paid")

    assert first == (True, 70, 2500)
    assert second == (False, 70, 2500)
    assert (await settings.get(70)).balance_kopecks == 2500


async def test_expired_crypto_invoice_does_not_credit_balance(tmp_path: Path) -> None:
    settings, payments = await _repositories(tmp_path)
    await settings.get(71)
    await payments.create_crypto_invoice(778, 71, 1000, "https://t.me/CryptoBot?start=invoice")

    result = await payments.settle_crypto_invoice(778, "expired")

    assert result == (True, 71, 0)
