from __future__ import annotations

import pytest

from app.repositories.payments import PaymentRepository
from app.repositories.settings import SettingsRepository
from app.services.errors import PaymentStateError


@pytest.fixture
async def repositories(tmp_path):
    database = tmp_path / "bot.sqlite3"
    settings = SettingsRepository(database, new_user_bonus_kopecks=1_000)
    await settings.initialize()
    payments = PaymentRepository(database)
    await payments.initialize()
    for user_id in (100, 200, 300):
        await settings.get(user_id)
    return settings, payments


async def approve_direct(
    payments: PaymentRepository,
    user_id: int,
    amount: int,
    suffix: str,
):
    payment = await payments.create_direct(user_id, amount)
    await payments.attach_receipt(
        payment.id,
        user_id,
        f"file-{suffix}",
        f"unique-{suffix}",
        "photo",
    )
    return await payments.approve(payment.id)


async def test_referral_activation_and_recurring_commission(repositories):
    settings, payments = repositories
    assert await payments.bind_referrer(200, 100)

    below_threshold = await approve_direct(payments, 200, 4_900, "below")
    assert below_threshold.referral_reward is None
    initial_summary = await payments.referral_summary(100)
    assert (
        initial_summary.invited,
        initial_summary.activated,
        initial_summary.earned_kopecks,
    ) == (1, 0, 0)

    activation = await approve_direct(payments, 200, 5_000, "activation")
    assert activation.referral_reward is not None
    assert activation.referral_reward.amount_kopecks == 2_000
    assert activation.referral_reward.kind == "activation"

    commission = await approve_direct(payments, 200, 10_000, "commission")
    assert commission.referral_reward is not None
    assert commission.referral_reward.amount_kopecks == 1_500
    assert commission.referral_reward.kind == "commission"

    summary = await payments.referral_summary(100)
    assert (summary.invited, summary.activated, summary.earned_kopecks) == (1, 1, 3_500)
    assert (await settings.get(100)).balance_kopecks == 4_500


async def test_referral_payment_is_idempotent(repositories):
    _, payments = repositories
    assert await payments.bind_referrer(200, 100)
    payment = await payments.create_direct(200, 5_000)
    await payments.attach_receipt(payment.id, 200, "file", "unique", "photo")

    first = await payments.approve(payment.id)
    second = await payments.approve(payment.id)

    assert first.referral_reward is not None
    assert not second.applied
    assert second.referral_reward is None
    assert (await payments.referral_summary(100)).earned_kopecks == 2_000


async def test_self_referral_and_duplicate_receipt_are_rejected(repositories):
    _, payments = repositories
    assert not await payments.bind_referrer(100, 100)

    first = await payments.create_direct(200, 5_000)
    await payments.attach_receipt(first.id, 200, "file-1", "same-receipt", "photo")
    second = await payments.create_direct(300, 5_000)
    with pytest.raises(PaymentStateError, match="уже использовался"):
        await payments.attach_receipt(second.id, 300, "file-2", "same-receipt", "photo")
