from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InputMediaAnimation, Message

from app.bot.banners import BannerMedia, BannerService
from app.config import Settings
from app.repositories import SettingsRepository

ContentFactory = Callable[[bool], tuple[str, InlineKeyboardMarkup]]
MediaOperation = Callable[[BannerMedia], Awaitable[Message | bool]]


class PanelService:
    def __init__(
        self,
        bot: Bot,
        repository: SettingsRepository,
        settings: Settings,
        banners: BannerService,
    ) -> None:
        self._bot = bot
        self._repository = repository
        self._banners = banners
        self._premium_enabled = settings.enable_custom_button_emoji

    async def show(
        self,
        user_id: int,
        chat_id: int,
        factory: ContentFactory,
        *,
        banner: str | None = "start",
    ) -> Message | None:
        attempts = [True, False] if self._premium_enabled else [False]
        last_error: TelegramBadRequest | None = None
        for premium in attempts:
            text, keyboard = factory(premium)
            try:
                return await self._upsert(user_id, chat_id, text, keyboard, banner)
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
        *,
        banner: str = "start",
    ) -> Message | None:
        panel = await self._repository.get_panel(user_id)
        if panel and panel[0] == chat_id:
            try:
                await self._bot.delete_message(chat_id, panel[1])
            except TelegramBadRequest:
                pass
        await self._repository.clear_panel(user_id)
        return await self.show(user_id, chat_id, factory, banner=banner)

    async def _upsert(
        self,
        user_id: int,
        chat_id: int,
        text: str,
        keyboard: InlineKeyboardMarkup,
        banner: str | None,
    ) -> Message | None:
        panel = await self._repository.get_panel(user_id)
        current_banner = await self._repository.get_panel_banner(user_id)
        desired_banner = banner or current_banner or "start"
        if panel and panel[0] == chat_id:
            try:
                if current_banner == desired_banner:
                    edited = await self._bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=panel[1],
                        caption=text,
                        reply_markup=keyboard,
                    )
                else:
                    edited = await self._with_cached_retry(
                        desired_banner,
                        lambda media: self._bot.edit_message_media(
                            chat_id=chat_id,
                            message_id=panel[1],
                            media=InputMediaAnimation(
                                media=media.media,
                                caption=text,
                                parse_mode="HTML",
                            ),
                            reply_markup=keyboard,
                        ),
                    )
                    await self._repository.set_panel_banner(user_id, desired_banner)
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
        sent = await self._with_cached_retry(
            desired_banner,
            lambda media: self._bot.send_animation(
                chat_id,
                media.media,
                caption=text,
                reply_markup=keyboard,
            ),
        )
        if not isinstance(sent, Message):
            raise RuntimeError("sendAnimation did not return a message")
        await self._repository.set_panel(user_id, chat_id, sent.message_id)
        await self._repository.set_panel_banner(user_id, desired_banner)
        return sent

    async def _with_cached_retry(
        self,
        banner_key: str,
        operation: MediaOperation,
    ) -> Message | bool:
        media = await self._banners.resolve(banner_key)
        try:
            result = await operation(media)
        except TelegramBadRequest as error:
            if not media.cached or not self._invalid_file_id(error):
                raise
            await self._banners.invalidate(banner_key)
            media = await self._banners.resolve(banner_key)
            result = await operation(media)
        if isinstance(result, Message) and result.animation:
            await self._banners.remember(media, result.animation.file_id)
        return result

    @staticmethod
    def _invalid_file_id(error: TelegramBadRequest) -> bool:
        description = str(error).lower()
        return any(
            marker in description
            for marker in (
                "wrong file identifier",
                "invalid file id",
                "file reference expired",
                "failed to get http url content",
            )
        )

    async def delete_user_message(self, message: Message) -> None:
        try:
            await self._bot.delete_message(message.chat.id, message.message_id)
        except TelegramBadRequest:
            pass
