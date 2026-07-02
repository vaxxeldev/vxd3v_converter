from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from aiogram.types import Chat, InlineKeyboardMarkup, Message

from app.bot.panel import PanelService
from app.config import Settings
from app.repositories import SettingsRepository


class FakeBot:
    def __init__(self) -> None:
        self.sent = 0
        self.edited = 0
        self.deleted: list[int] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> Message:
        self.sent += 1
        return Message(
            message_id=100,
            date=datetime.now(UTC),
            chat=Chat(id=chat_id, type="private"),
            text=text,
        )

    async def edit_message_text(self, **kwargs) -> Message:
        self.edited += 1
        return Message(
            message_id=kwargs["message_id"],
            date=datetime.now(UTC),
            chat=Chat(id=kwargs["chat_id"], type="private"),
            text=kwargs["text"],
        )

    async def delete_message(self, chat_id: int, message_id: int) -> bool:
        self.deleted.append(message_id)
        return True


def _factory(premium: bool) -> tuple[str, InlineKeyboardMarkup]:
    marker = "premium" if premium else "plain"
    return marker, InlineKeyboardMarkup(inline_keyboard=[])


async def test_panel_is_created_once_and_then_edited(tmp_path: Path) -> None:
    repository = SettingsRepository(tmp_path / "bot.sqlite3")
    await repository.initialize()
    bot = FakeBot()
    panel = PanelService(bot, repository, Settings(enable_custom_button_emoji=True))  # type: ignore[arg-type]

    await panel.show(1, 1, _factory)
    await panel.show(1, 1, _factory)

    assert bot.sent == 1
    assert bot.edited == 1
    assert await repository.get_panel(1) == (1, 100)


async def test_user_input_can_be_deleted_without_reply(tmp_path: Path) -> None:
    repository = SettingsRepository(tmp_path / "bot.sqlite3")
    await repository.initialize()
    bot = FakeBot()
    panel = PanelService(bot, repository, Settings())  # type: ignore[arg-type]
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
    repository = SettingsRepository(tmp_path / "bot.sqlite3")
    await repository.initialize()
    await repository.set_panel(1, 1, 77)
    bot = FakeBot()
    panel = PanelService(bot, repository, Settings())  # type: ignore[arg-type]

    await panel.recreate(1, 1, _factory)

    assert bot.deleted == [77]
    assert bot.edited == 0
    assert bot.sent == 1
    assert await repository.get_panel(1) == (1, 100)
