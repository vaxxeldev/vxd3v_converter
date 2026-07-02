from __future__ import annotations

from collections.abc import Callable

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message

from app.config import Settings
from app.repositories import SettingsRepository

ContentFactory = Callable[[bool], tuple[str, InlineKeyboardMarkup]]


class PanelService:
    def __init__(
        self,
        bot: Bot,
        repository: SettingsRepository,
        settings: Settings,
    ) -> None:
        self._bot = bot
        self._repository = repository
        self._premium_enabled = settings.enable_custom_button_emoji

    async def show(
        self,
        user_id: int,
        chat_id: int,
        factory: ContentFactory,
    ) -> Message | None:
        attempts = [True, False] if self._premium_enabled else [False]
        last_error: TelegramBadRequest | None = None
        for premium in attempts:
            text, keyboard = factory(premium)
            try:
                return await self._upsert(user_id, chat_id, text, keyboard)
            except TelegramBadRequest as error:
                if "message is not modified" in str(error).lower():
                    return None
                last_error = error
        if last_error is not None:
            raise last_error
        return None

    async def recreate(
        self,
        user_id: int,
        chat_id: int,
        factory: ContentFactory,
    ) -> Message | None:
        panel = await self._repository.get_panel(user_id)
        if panel and panel[0] == chat_id:
            try:
                await self._bot.delete_message(chat_id, panel[1])
            except TelegramBadRequest:
                pass
        await self._repository.clear_panel(user_id)
        return await self.show(user_id, chat_id, factory)

    async def _upsert(
        self,
        user_id: int,
        chat_id: int,
        text: str,
        keyboard: InlineKeyboardMarkup,
    ) -> Message | None:
        panel = await self._repository.get_panel(user_id)
        if panel and panel[0] == chat_id:
            try:
                edited = await self._bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=panel[1],
                    text=text,
                    reply_markup=keyboard,
                )
                return edited if isinstance(edited, Message) else None
            except TelegramBadRequest as error:
                description = str(error).lower()
                if "message is not modified" in description:
                    return None
                if not any(
                    marker in description
                    for marker in ("message to edit not found", "message can't be edited")
                ):
                    raise
                await self._repository.clear_panel(user_id)
        sent = await self._bot.send_message(chat_id, text, reply_markup=keyboard)
        await self._repository.set_panel(user_id, chat_id, sent.message_id)
        return sent

    async def delete_user_message(self, message: Message) -> None:
        try:
            await self._bot.delete_message(message.chat.id, message.message_id)
        except TelegramBadRequest:
            pass
