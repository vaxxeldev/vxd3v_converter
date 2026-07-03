from __future__ import annotations

import asyncio
import json
import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity

from app.repositories.broadcasts import BroadcastJob, BroadcastRecipient, BroadcastRepository

logger = logging.getLogger(__name__)


class BroadcastService:
    def __init__(self, repository: BroadcastRepository) -> None:
        self._repository = repository

    async def run(self, bot: Bot) -> None:
        while True:
            try:
                job = await self._repository.active_job()
                if job is None:
                    await asyncio.sleep(1)
                    continue
                await self._run_job(bot, job)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Broadcast worker failed")
                await asyncio.sleep(3)

    async def _run_job(self, bot: Bot, job: BroadcastJob) -> None:
        processed_since_update = 0
        while True:
            recipient = await self._repository.claim_recipient(job.id)
            if recipient is None:
                job = await self._repository.finish_if_complete(job.id)
                await self._update_status(bot, job)
                return
            should_continue = await self._deliver(bot, job, recipient)
            if not should_continue:
                failed = await self._repository.fail_job(job.id, "invalid_content")
                await self._update_status(bot, failed)
                return
            processed_since_update += 1
            if processed_since_update >= 10:
                current = await self._repository.job(job.id)
                if current:
                    await self._update_status(bot, current)
                processed_since_update = 0
            await asyncio.sleep(0.055)

    async def _deliver(
        self, bot: Bot, job: BroadcastJob, recipient: BroadcastRecipient
    ) -> bool:
        try:
            await self.send_payload(bot, recipient.user_id, job)
        except TelegramRetryAfter as error:
            await self._repository.mark_recipient(recipient, "pending", "rate_limit")
            await asyncio.sleep(max(float(error.retry_after), 1.0))
            return True
        except TelegramForbiddenError:
            await self._repository.mark_recipient(recipient, "blocked", "forbidden")
            return True
        except TelegramBadRequest as error:
            message = str(error).casefold()
            blocked = "chat not found" in message or "user is deactivated" in message
            await self._repository.mark_recipient(
                recipient,
                "blocked" if blocked else "failed",
                "unreachable" if blocked else "bad_request",
            )
            return blocked
        except TelegramNetworkError:
            if recipient.attempts < 3:
                await self._repository.mark_recipient(recipient, "pending", "network")
                await asyncio.sleep(recipient.attempts)
            else:
                await self._repository.mark_recipient(recipient, "failed", "network")
            return True
        else:
            await self._repository.mark_recipient(recipient, "sent", None)
            return True

    @staticmethod
    async def send_payload(bot: Bot, chat_id: int, job: BroadcastJob):
        entities = None
        if job.entities_json:
            entities = [
                MessageEntity.model_validate(item) for item in json.loads(job.entities_json)
            ]
        markup = None
        if job.button_url and (job.button_text or job.button_emoji_id):
            extra = {}
            if job.button_emoji_id:
                extra["icon_custom_emoji_id"] = job.button_emoji_id
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=job.button_text or "·",
                            url=job.button_url,
                            **extra,
                        )
                    ]
                ]
            )
        common = {"reply_markup": markup, "parse_mode": None}
        if job.media_type == "photo":
            return await bot.send_photo(
                chat_id,
                job.media_file_id,
                caption=job.text,
                caption_entities=entities,
                **common,
            )
        if job.media_type == "video":
            return await bot.send_video(
                chat_id,
                job.media_file_id,
                caption=job.text,
                caption_entities=entities,
                **common,
            )
        if job.media_type == "animation":
            return await bot.send_animation(
                chat_id,
                job.media_file_id,
                caption=job.text,
                caption_entities=entities,
                **common,
            )
        return await bot.send_message(
            chat_id,
            job.text or "",
            entities=entities,
            **common,
        )

    @staticmethod
    async def _update_status(bot: Bot, job: BroadcastJob) -> None:
        if job.status_chat_id is None or job.status_message_id is None:
            return
        processed = job.sent + job.blocked + job.failed
        title = (
            "Рассылка завершена"
            if job.status == "completed"
            else "Рассылка остановлена"
            if job.status == "failed"
            else "Рассылка выполняется"
        )
        text = (
            f"📤 <b>{title}</b>\n\n"
            f"Обработано: <code>{processed}/{job.total}</code>\n"
            f"Доставлено: <code>{job.sent}</code>\n"
            f"Заблокировали бота: <code>{job.blocked}</code>\n"
            f"Ошибки: <code>{job.failed}</code>"
        )
        try:
            await bot.edit_message_text(
                text,
                chat_id=job.status_chat_id,
                message_id=job.status_message_id,
            )
        except TelegramBadRequest as error:
            if "message is not modified" not in str(error).casefold():
                logger.warning("Unable to update broadcast status code=bad_request")
