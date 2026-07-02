from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Animation, Chat, InlineKeyboardMarkup, Message

from app.bot.banners import BannerService
from app.bot.panel import PanelService
from app.config import Settings
from app.repositories import SettingsRepository


class FakeBot:
    def __init__(self) -> None:
        self.sent = 0
        self.caption_edits = 0
        self.media_edits = 0
        self.deleted: list[int] = []
        self.used_media: list[Any] = []
        self.stale_file_ids: set[str] = set()

    @staticmethod
    def _message(chat_id: int, message_id: int = 100) -> Message:
        return Message(
            message_id=message_id,
            date=datetime.now(UTC),
            chat=Chat(id=chat_id, type="private"),
            animation=Animation(
                file_id="telegram-file-id",
                file_unique_id="telegram-unique-id",
                width=1920,
                height=530,
                duration=3,
            ),
        )

    async def send_animation(self, chat_id: int, animation: Any, **kwargs: Any) -> Message:
        self.sent += 1
        self.used_media.append(animation)
        return self._message(chat_id)

    async def edit_message_caption(self, **kwargs: Any) -> Message:
        self.caption_edits += 1
        return self._message(kwargs["chat_id"], kwargs["message_id"])

    async def edit_message_media(self, **kwargs: Any) -> Message:
        self.media_edits += 1
        media = kwargs["media"].media
        self.used_media.append(media)
        if media in self.stale_file_ids:
            raise TelegramBadRequest(  # type: ignore[arg-type]
                method=object(),
                message="Bad Request: wrong file identifier/HTTP URL specified",
            )
        return self._message(kwargs["chat_id"], kwargs["message_id"])

    async def delete_message(self, chat_id: int, message_id: int) -> bool:
        self.deleted.append(message_id)
        return True


def _factory(premium: bool) -> tuple[str, InlineKeyboardMarkup]:
    marker = "premium" if premium else "plain"
    return marker, InlineKeyboardMarkup(inline_keyboard=[])


def _write_banner(root: Path, name: str = "старт.mp4", content: bytes = b"video") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_bytes(content)


async def _panel(tmp_path: Path) -> tuple[PanelService, SettingsRepository, FakeBot]:
    repository = SettingsRepository(tmp_path / "bot.sqlite3")
    await repository.initialize()
    _write_banner(tmp_path / "banners")
    _write_banner(tmp_path / "banners", "размеры.mp4", b"size-video")
    bot = FakeBot()
    settings = Settings(banner_root=tmp_path / "banners", enable_custom_button_emoji=True)
    banners = BannerService(settings, repository)
    panel = PanelService(bot, repository, settings, banners)  # type: ignore[arg-type]
    return panel, repository, bot


async def test_panel_is_created_once_then_only_caption_is_edited(tmp_path: Path) -> None:
    panel, repository, bot = await _panel(tmp_path)

    await panel.show(1, 1, _factory)
    await panel.show(1, 1, _factory)

    assert bot.sent == 1
    assert bot.caption_edits == 1
    assert bot.media_edits == 0
    assert await repository.get_panel(1) == (1, 100)
    assert await repository.get_panel_banner(1) == "start"


async def test_switching_screen_edits_media_once(tmp_path: Path) -> None:
    panel, repository, bot = await _panel(tmp_path)
    await panel.show(1, 1, _factory)

    await panel.show(1, 1, _factory, banner="size")

    assert bot.sent == 1
    assert bot.media_edits == 1
    assert await repository.get_panel_banner(1) == "size"
    assert await repository.get_banner_cache("size") is not None


async def test_user_input_can_be_deleted_without_reply(tmp_path: Path) -> None:
    panel, _, bot = await _panel(tmp_path)
    message = Message(
        message_id=55,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
        text="#FFFFFF",
    )

    await panel.delete_user_message(message)

    assert bot.deleted == [55]
    assert bot.sent == 0


async def test_explicit_start_recreates_panel_after_chat_history_clear(
    tmp_path: Path,
) -> None:
    panel, repository, bot = await _panel(tmp_path)
    await repository.set_panel(1, 1, 77)
    await repository.set_panel_banner(1, "start")

    await panel.recreate(1, 1, _factory)

    assert bot.deleted == [77]
    assert bot.caption_edits == 0
    assert bot.sent == 1
    assert await repository.get_panel(1) == (1, 100)


async def test_stale_telegram_file_id_is_reuploaded_once(tmp_path: Path) -> None:
    panel, repository, bot = await _panel(tmp_path)
    await panel.show(1, 1, _factory)
    settings = Settings(banner_root=tmp_path / "banners")
    cache_loader = BannerService(settings, repository)
    size_media = await cache_loader.resolve("size")
    await cache_loader.remember(size_media, "stale-id")
    bot.stale_file_ids.add("stale-id")

    await panel.show(1, 1, _factory, banner="size")

    assert bot.media_edits == 2
    assert bot.used_media[-2] == "stale-id"
    assert bot.used_media[-1] != "stale-id"
    cached = await repository.get_banner_cache("size")
    assert cached is not None
    assert cached[1] == "telegram-file-id"
