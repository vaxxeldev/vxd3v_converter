from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path

import aiosqlite


@dataclass(slots=True, frozen=True)
class BroadcastDraft:
    admin_id: int
    state: str
    text: str | None
    entities_json: str | None
    media_type: str | None
    media_file_id: str | None
    button_text: str | None
    button_url: str | None
    button_emoji_id: str | None
    control_chat_id: int | None
    control_message_id: int | None
    preview_message_id: int | None


@dataclass(slots=True, frozen=True)
class BroadcastJob:
    id: str
    admin_id: int
    text: str | None
    entities_json: str | None
    media_type: str | None
    media_file_id: str | None
    button_text: str | None
    button_url: str | None
    button_emoji_id: str | None
    status: str
    total: int
    sent: int
    blocked: int
    failed: int
    status_chat_id: int | None
    status_message_id: int | None


@dataclass(slots=True, frozen=True)
class BroadcastRecipient:
    job_id: str
    user_id: int
    attempts: int


class BroadcastRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    async def initialize(self) -> None:
        await asyncio.to_thread(self._database_path.parent.mkdir, parents=True, exist_ok=True)
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS broadcast_drafts (
                    admin_id INTEGER PRIMARY KEY,
                    state TEXT NOT NULL,
                    text TEXT,
                    entities_json TEXT,
                    media_type TEXT,
                    media_file_id TEXT,
                    button_text TEXT,
                    button_url TEXT,
                    button_emoji_id TEXT,
                    control_chat_id INTEGER,
                    control_message_id INTEGER,
                    preview_message_id INTEGER,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS broadcast_jobs (
                    id TEXT PRIMARY KEY,
                    admin_id INTEGER NOT NULL,
                    text TEXT,
                    entities_json TEXT,
                    media_type TEXT,
                    media_file_id TEXT,
                    button_text TEXT,
                    button_url TEXT,
                    button_emoji_id TEXT,
                    status TEXT NOT NULL,
                    total INTEGER NOT NULL DEFAULT 0,
                    sent INTEGER NOT NULL DEFAULT 0,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    status_chat_id INTEGER,
                    status_message_id INTEGER,
                    last_error_code TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_broadcast
                ON broadcast_jobs(status) WHERE status IN ('pending', 'running');
                CREATE TABLE IF NOT EXISTS broadcast_recipients (
                    job_id TEXT NOT NULL REFERENCES broadcast_jobs(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error_code TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(job_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS broadcast_recipient_queue
                ON broadcast_recipients(job_id, status, user_id);
                UPDATE broadcast_recipients SET status = 'pending'
                WHERE status = 'sending';
                UPDATE broadcast_jobs SET status = 'pending'
                WHERE status = 'running';
                """
            )
            await connection.commit()

    async def start_draft(self, admin_id: int, chat_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute(
                "INSERT INTO broadcast_drafts "
                "(admin_id, state, control_chat_id, control_message_id) VALUES (?, 'text', ?, ?) "
                "ON CONFLICT(admin_id) DO UPDATE SET state = 'text', text = NULL, "
                "entities_json = NULL, media_type = NULL, media_file_id = NULL, "
                "button_text = NULL, button_url = NULL, button_emoji_id = NULL, "
                "control_chat_id = excluded.control_chat_id, "
                "control_message_id = excluded.control_message_id, preview_message_id = NULL, "
                "updated_at = CURRENT_TIMESTAMP",
                (admin_id, chat_id, message_id),
            )
            await connection.commit()

    async def draft(self, admin_id: int) -> BroadcastDraft | None:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT * FROM broadcast_drafts WHERE admin_id = ?", (admin_id,)
            )
            row = await cursor.fetchone()
        return None if row is None else self._draft(row)

    async def update_draft(self, admin_id: int, *, state: str, **values: object) -> None:
        allowed = {
            "text",
            "entities_json",
            "media_type",
            "media_file_id",
            "button_text",
            "button_url",
            "button_emoji_id",
            "control_chat_id",
            "control_message_id",
            "preview_message_id",
        }
        if not set(values).issubset(allowed):
            raise ValueError("unsupported broadcast draft field")
        assignments = ["state = ?", *[f"{name} = ?" for name in values]]
        parameters = [state, *values.values(), admin_id]
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute(
                f"UPDATE broadcast_drafts SET {', '.join(assignments)}, "  # noqa: S608
                "updated_at = CURRENT_TIMESTAMP WHERE admin_id = ?",
                parameters,
            )
            await connection.commit()

    async def delete_draft(self, admin_id: int) -> None:
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute("DELETE FROM broadcast_drafts WHERE admin_id = ?", (admin_id,))
            await connection.commit()

    async def create_job(
        self, admin_id: int, status_chat_id: int, status_message_id: int
    ) -> BroadcastJob:
        job_id = uuid.uuid4().hex
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("BEGIN IMMEDIATE")
            active = await connection.execute(
                "SELECT 1 FROM broadcast_jobs WHERE status IN ('pending', 'running') LIMIT 1"
            )
            if await active.fetchone() is not None:
                await connection.rollback()
                raise RuntimeError("broadcast already active")
            draft_cursor = await connection.execute(
                "SELECT * FROM broadcast_drafts WHERE admin_id = ?", (admin_id,)
            )
            draft = await draft_cursor.fetchone()
            if draft is None or draft["state"] != "preview":
                await connection.rollback()
                raise RuntimeError("broadcast draft is not ready")
            await connection.execute(
                "INSERT INTO broadcast_jobs "
                "(id, admin_id, text, entities_json, media_type, media_file_id, button_text, "
                "button_url, button_emoji_id, status, status_chat_id, status_message_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                (
                    job_id,
                    admin_id,
                    draft["text"],
                    draft["entities_json"],
                    draft["media_type"],
                    draft["media_file_id"],
                    draft["button_text"],
                    draft["button_url"],
                    draft["button_emoji_id"],
                    status_chat_id,
                    status_message_id,
                ),
            )
            await connection.execute(
                "INSERT INTO broadcast_recipients (job_id, user_id) "
                "SELECT ?, user_id FROM user_settings WHERE user_id <> ? "
                "AND COALESCE(delivery_status, 'unknown') <> 'blocked'",
                (job_id, admin_id),
            )
            count_cursor = await connection.execute(
                "SELECT COUNT(*) FROM broadcast_recipients WHERE job_id = ?", (job_id,)
            )
            total = int((await count_cursor.fetchone())[0])
            await connection.execute(
                "UPDATE broadcast_jobs SET total = ? WHERE id = ?", (total, job_id)
            )
            await connection.execute("DELETE FROM broadcast_drafts WHERE admin_id = ?", (admin_id,))
            await connection.commit()
        job = await self.job(job_id)
        if job is None:
            raise RuntimeError("failed to create broadcast")
        return job

    async def active_job(self) -> BroadcastJob | None:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT * FROM broadcast_jobs WHERE status IN ('pending', 'running') "
                "ORDER BY created_at LIMIT 1"
            )
            row = await cursor.fetchone()
        return None if row is None else self._job(row)

    async def job(self, job_id: str) -> BroadcastJob | None:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT * FROM broadcast_jobs WHERE id = ?", (job_id,)
            )
            row = await cursor.fetchone()
        return None if row is None else self._job(row)

    async def claim_recipient(self, job_id: str) -> BroadcastRecipient | None:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                "UPDATE broadcast_jobs SET status = 'running', updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'pending'",
                (job_id,),
            )
            cursor = await connection.execute(
                "SELECT user_id, attempts FROM broadcast_recipients "
                "WHERE job_id = ? AND status = 'pending' ORDER BY user_id LIMIT 1",
                (job_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                await connection.commit()
                return None
            await connection.execute(
                "UPDATE broadcast_recipients SET status = 'sending', attempts = attempts + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE job_id = ? AND user_id = ?",
                (job_id, row["user_id"]),
            )
            await connection.commit()
        return BroadcastRecipient(job_id, int(row["user_id"]), int(row["attempts"]) + 1)

    async def mark_recipient(
        self, recipient: BroadcastRecipient, status: str, code: str | None
    ) -> None:
        if status not in {"pending", "sent", "blocked", "failed"}:
            raise ValueError("unsupported broadcast recipient status")
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                "UPDATE broadcast_recipients SET status = ?, last_error_code = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE job_id = ? AND user_id = ?",
                (status, code, recipient.job_id, recipient.user_id),
            )
            if status in {"sent", "blocked", "failed"}:
                await connection.execute(
                    f"UPDATE broadcast_jobs SET {status} = {status} + 1, "  # noqa: S608
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (recipient.job_id,),
                )
            delivery_status = (
                "active" if status == "sent" else "blocked" if status == "blocked" else None
            )
            if delivery_status:
                await connection.execute(
                    "UPDATE user_settings SET delivery_status = ?, delivery_checked_at = "
                    "CURRENT_TIMESTAMP WHERE user_id = ?",
                    (delivery_status, recipient.user_id),
                )
            await connection.commit()

    async def finish_if_complete(self, job_id: str) -> BroadcastJob:
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            pending = await connection.execute(
                "SELECT COUNT(*) FROM broadcast_recipients WHERE job_id = ? "
                "AND status IN ('pending', 'sending')",
                (job_id,),
            )
            if int((await pending.fetchone())[0]) == 0:
                await connection.execute(
                    "UPDATE broadcast_jobs SET status = 'completed', "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND status IN ('pending', 'running')",
                    (job_id,),
                )
            await connection.commit()
        job = await self.job(job_id)
        if job is None:
            raise RuntimeError("broadcast job disappeared")
        return job

    async def fail_job(self, job_id: str, code: str) -> BroadcastJob:
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "SELECT COUNT(*) FROM broadcast_recipients WHERE job_id = ? "
                "AND status IN ('pending', 'sending')",
                (job_id,),
            )
            remaining = int((await cursor.fetchone())[0])
            await connection.execute(
                "UPDATE broadcast_recipients SET status = 'failed', last_error_code = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE job_id = ? "
                "AND status IN ('pending', 'sending')",
                (code, job_id),
            )
            await connection.execute(
                "UPDATE broadcast_jobs SET status = 'failed', failed = failed + ?, "
                "last_error_code = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (remaining, code, job_id),
            )
            await connection.commit()
        job = await self.job(job_id)
        if job is None:
            raise RuntimeError("broadcast job disappeared")
        return job

    @staticmethod
    def _draft(row: aiosqlite.Row) -> BroadcastDraft:
        return BroadcastDraft(*(row[name] for name in BroadcastDraft.__dataclass_fields__))

    @staticmethod
    def _job(row: aiosqlite.Row) -> BroadcastJob:
        return BroadcastJob(*(row[name] for name in BroadcastJob.__dataclass_fields__))
