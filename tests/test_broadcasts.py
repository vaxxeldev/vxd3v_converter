from __future__ import annotations

import json

import aiosqlite
import pytest

from app.repositories.broadcasts import BroadcastJob, BroadcastRepository
from app.repositories.payments import PaymentRepository
from app.repositories.settings import SettingsRepository
from app.services.broadcast import BroadcastService


@pytest.fixture
async def repositories(tmp_path):
    database = tmp_path / "bot.sqlite3"
    settings = SettingsRepository(database)
    await settings.initialize()
    payments = PaymentRepository(database)
    await payments.initialize()
    broadcasts = BroadcastRepository(database)
    await broadcasts.initialize()
    for user_id in (1, 10, 20, 30):
        await settings.get(user_id)
    return database, settings, payments, broadcasts


async def ready_draft(repository: BroadcastRepository, admin_id: int = 1) -> None:
    await repository.start_draft(admin_id, admin_id, 100)
    await repository.update_draft(
        admin_id,
        state="preview",
        text="Hello",
        entities_json="[]",
        media_type=None,
        media_file_id=None,
        button_text=None,
        button_url=None,
        button_emoji_id=None,
    )


async def test_job_targets_all_non_blocked_users_once(repositories):
    database, _, _, broadcasts = repositories
    async with aiosqlite.connect(database) as connection:
        await connection.execute(
            "UPDATE user_settings SET delivery_status = 'blocked' WHERE user_id = 30"
        )
        await connection.commit()
    await ready_draft(broadcasts)

    job = await broadcasts.create_job(1, 1, 100)
    assert job.total == 2

    first = await broadcasts.claim_recipient(job.id)
    second = await broadcasts.claim_recipient(job.id)
    assert first is not None and second is not None
    assert {first.user_id, second.user_id} == {10, 20}
    await broadcasts.mark_recipient(first, "sent", None)
    await broadcasts.mark_recipient(second, "failed", "network")
    assert await broadcasts.claim_recipient(job.id) is None

    completed = await broadcasts.finish_if_complete(job.id)
    assert completed.status == "completed"
    assert (completed.sent, completed.failed, completed.blocked) == (1, 1, 0)


async def test_active_job_prevents_duplicate_launch(repositories):
    _, _, _, broadcasts = repositories
    await ready_draft(broadcasts)
    await broadcasts.create_job(1, 1, 100)
    await ready_draft(broadcasts, admin_id=10)

    with pytest.raises(RuntimeError, match="already active"):
        await broadcasts.create_job(10, 10, 200)


async def test_fatal_content_error_stops_remaining_delivery(repositories):
    _, _, _, broadcasts = repositories
    await ready_draft(broadcasts)
    job = await broadcasts.create_job(1, 1, 100)
    first = await broadcasts.claim_recipient(job.id)
    assert first is not None
    await broadcasts.mark_recipient(first, "failed", "bad_request")

    failed = await broadcasts.fail_job(job.id, "invalid_content")

    assert failed.status == "failed"
    assert failed.failed == failed.total
    assert await broadcasts.claim_recipient(job.id) is None


async def test_restart_recovers_claimed_recipient(repositories):
    database, _, _, broadcasts = repositories
    await ready_draft(broadcasts)
    job = await broadcasts.create_job(1, 1, 100)
    claimed = await broadcasts.claim_recipient(job.id)
    assert claimed is not None

    restarted = BroadcastRepository(database)
    await restarted.initialize()
    recovered = await restarted.claim_recipient(job.id)
    assert recovered is not None
    assert recovered.user_id == claimed.user_id
    assert recovered.attempts == 2


async def test_statistics_are_consistent_and_exclude_admin(repositories):
    database, _, payments, broadcasts = repositories
    async with aiosqlite.connect(database) as connection:
        await connection.execute(
            "UPDATE user_settings SET delivery_status = 'active' WHERE user_id IN (10, 20)"
        )
        await connection.execute(
            "UPDATE user_settings SET delivery_status = 'blocked' WHERE user_id = 30"
        )
        await connection.commit()
    await ready_draft(broadcasts)
    job = await broadcasts.create_job(1, 1, 100)
    while recipient := await broadcasts.claim_recipient(job.id):
        await broadcasts.mark_recipient(recipient, "sent", None)
    await broadcasts.finish_if_complete(job.id)

    stats = await payments.statistics(1)
    assert stats.users_total == 3
    assert stats.users_reachable == 2
    assert stats.users_blocked == 1
    assert stats.broadcasts_completed == 1
    assert stats.broadcast_delivered == 2


class FakeBot:
    def __init__(self) -> None:
        self.calls = []

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append((chat_id, text, kwargs))
        return object()


async def test_payload_preserves_entities_and_button():
    bot = FakeBot()
    entities = [{"type": "bold", "offset": 0, "length": 5}]
    job = BroadcastJob(
        "job",
        1,
        "Hello",
        json.dumps(entities),
        None,
        None,
        "Open",
        "https://example.com",
        None,
        "running",
        1,
        0,
        0,
        0,
        None,
        None,
    )

    await BroadcastService.send_payload(bot, 10, job)

    assert len(bot.calls) == 1
    chat_id, text, kwargs = bot.calls[0]
    assert (chat_id, text) == (10, "Hello")
    assert kwargs["entities"][0].type == "bold"
    assert kwargs["reply_markup"].inline_keyboard[0][0].url == "https://example.com"
