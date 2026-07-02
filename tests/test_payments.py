from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from app.bot.payment_handlers import is_admin
from app.config import Settings
from app.repositories import PaymentRepository, SettingsRepository
from app.repositories.payments import PaymentStatus
from app.services.crypto_pay import CryptoPayClient
from app.services.errors import InsufficientBalanceError, PaymentStateError
from app.services.payments import format_rubles, parse_rubles


async def _repositories(tmp_path: Path) -> tuple[SettingsRepository, PaymentRepository]:
    database = tmp_path / "bot.sqlite3"
    settings = SettingsRepository(database)
    await settings.initialize()
    payments = PaymentRepository(database)
    await payments.initialize()
    return settings, payments


async def _balance_parts(database: Path, user_id: int) -> tuple[int, int]:
    async with aiosqlite.connect(database) as connection:
        cursor = await connection.execute(
            "SELECT balance_kopecks, admin_credit_balance_kopecks "
            "FROM user_settings WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


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


async def test_welcome_bonus_is_granted_once_only_to_new_users(tmp_path: Path) -> None:
    database = tmp_path / "bot.sqlite3"
    settings = SettingsRepository(database, new_user_bonus_kopecks=1000)
    await settings.initialize()
    payments = PaymentRepository(database)
    await payments.initialize()

    first = await settings.get(80)
    second = await settings.get(80)

    assert first.balance_kopecks == 1000
    assert second.balance_kopecks == 1000
    async with aiosqlite.connect(database) as connection:
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM balance_transactions "
            "WHERE user_id = 80 AND kind = 'welcome_bonus'"
        )
        assert await cursor.fetchone() == (1,)


async def test_existing_user_does_not_receive_welcome_bonus_after_update(tmp_path: Path) -> None:
    database = tmp_path / "bot.sqlite3"
    old_repository = SettingsRepository(database)
    await old_repository.initialize()
    await old_repository.get(81)
    payments = PaymentRepository(database)
    await payments.initialize()

    updated_repository = SettingsRepository(database, new_user_bonus_kopecks=1000)
    await updated_repository.initialize()

    assert (await updated_repository.get(81)).balance_kopecks == 0


async def test_admin_credit_is_spent_first_and_refunded_to_same_bucket(tmp_path: Path) -> None:
    settings, payments = await _repositories(tmp_path)
    await settings.get(90)
    await payments.admin_credit(90, 1500)
    request = await payments.create_direct(90, 1000)
    await payments.attach_receipt(request.id, 90, "receipt", "photo")
    await payments.approve(request.id)

    first = await payments.charge_render(90, 1000)
    second = await payments.charge_render(90, 1000)

    assert first.admin_credit_kopecks == 1000
    assert first.regular_kopecks == 0
    assert second.admin_credit_kopecks == 500
    assert second.regular_kopecks == 500
    assert await _balance_parts(tmp_path / "bot.sqlite3", 90) == (500, 0)

    assert await payments.refund_render(second.id) is True
    assert await _balance_parts(tmp_path / "bot.sqlite3", 90) == (1500, 500)


async def test_statistics_exclude_admin_and_manual_credit_balance(tmp_path: Path) -> None:
    database = tmp_path / "bot.sqlite3"
    settings = SettingsRepository(database, new_user_bonus_kopecks=1000)
    await settings.initialize()
    payments = PaymentRepository(database)
    await payments.initialize()
    admin_id = 2009632768
    await settings.get(admin_id)
    await settings.get(101)
    await settings.get(102)

    await payments.admin_credit(101, 5000)
    direct = await payments.create_direct(101, 2000)
    await payments.attach_receipt(direct.id, 101, "receipt", "photo")
    await payments.approve(direct.id)
    await payments.create_crypto_invoice(7001, 102, 3000, "https://t.me/CryptoBot?a=1")
    await payments.settle_crypto_invoice(7001, "paid")

    completed = await payments.charge_render(101, 1000)
    await payments.complete_render(completed.id)
    refunded = await payments.charge_render(102, 1000)
    await payments.refund_render(refunded.id)

    pending = await payments.create_direct(102, 1000)
    await payments.attach_receipt(pending.id, 102, "pending", "photo")
    await payments.create_crypto_invoice(7002, 102, 1000, "https://t.me/CryptoBot?a=2")

    stats = await payments.statistics(admin_id)

    assert stats.users_total == 2
    assert stats.users_today == 2
    assert stats.users_seven_days == 2
    assert stats.renders_completed == 1
    assert stats.renders_refunded == 1
    assert stats.successful_render_percent == 50.0
    assert stats.renders_per_user == 0.5
    assert stats.countable_balance_kopecks == 7000
    assert stats.direct_topups_kopecks == 2000
    assert stats.crypto_topups_kopecks == 3000
    assert stats.payments_awaiting_review == 1
    assert stats.crypto_invoices_active == 1
