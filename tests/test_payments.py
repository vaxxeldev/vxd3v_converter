from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from app.bot.payment_handlers import is_admin
from app.config import Settings
from app.models import UserSettings, WatermarkPosition
from app.repositories import PaymentRepository, SettingsRepository
from app.repositories.payments import PaymentStatus
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


def test_preview_forces_centered_vxd3v_watermark() -> None:
    source = UserSettings(
        user_id=1,
        watermark_text="custom",
        watermark_position=WatermarkPosition.TOP_LEFT,
    )

    preview = preview_settings(source)

    assert preview.watermark_text == "vxd3v"
    assert preview.watermark_position is WatermarkPosition.CENTER
    assert source.watermark_text == "custom"
