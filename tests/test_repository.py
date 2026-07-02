from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from app.models import BackgroundKind, OutputFormat, SourceAsset, StickerKind
from app.repositories import SettingsRepository


async def test_settings_persist_between_repository_instances(tmp_path: Path) -> None:
    database = tmp_path / "data" / "bot.sqlite3"
    first = SettingsRepository(database)
    await first.initialize()

    defaults = await first.get(42)
    updated = await first.update(
        42,
        background_kind=BackgroundKind.PHOTO,
        background_file_id="photo-id",
        emoji_size_percent=70,
    )
    await first.set_pending_action(42, "watermark")

    second = SettingsRepository(database)
    loaded = await second.get(42)
    assert defaults.background_color == "#F74539"
    assert updated.output_format is OutputFormat.ANIMATION
    assert loaded.background_kind is BackgroundKind.PHOTO
    assert loaded.background_file_id == "photo-id"
    assert loaded.emoji_size_percent == 70
    assert await second.get_pending_action(42) == "watermark"


async def test_repository_rejects_unknown_update_field(tmp_path: Path) -> None:
    repository = SettingsRepository(tmp_path / "bot.sqlite3")
    await repository.initialize()

    with pytest.raises(ValueError):
        await repository.update(1, is_admin=True)


async def test_initialize_migrates_legacy_formats_to_telegram_animation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "bot.sqlite3"
    repository = SettingsRepository(database)
    await repository.initialize()
    await repository.get(7)
    async with aiosqlite.connect(database) as connection:
        await connection.execute(
            "UPDATE user_settings SET output_format = 'file' WHERE user_id = 7"
        )
        await connection.commit()

    await repository.initialize()

    assert (await repository.get(7)).output_format is OutputFormat.ANIMATION


async def test_panel_and_last_sources_survive_restart(tmp_path: Path) -> None:
    database = tmp_path / "bot.sqlite3"
    first = SettingsRepository(database)
    await first.initialize()
    sources = [
        SourceAsset(
            file_id="file-id",
            file_unique_id="unique-id",
            kind=StickerKind.TGS,
            emoji="✨",
            custom_emoji_id="emoji-id",
            needs_repainting=True,
            premium_animation_file_id="effect-id",
        )
    ]

    await first.set_panel(11, 11, 900)
    await first.set_preview_message(11, 901)
    await first.set_sources(11, sources)

    second = SettingsRepository(database)
    await second.initialize()
    loaded = await second.get_sources(11)
    assert await second.get_panel(11) == (11, 900)
    assert await second.get_preview_message(11) == 901
    assert loaded == sources


async def test_corrupt_source_draft_is_ignored(tmp_path: Path) -> None:
    database = tmp_path / "bot.sqlite3"
    repository = SettingsRepository(database)
    await repository.initialize()
    await repository.get(12)
    async with aiosqlite.connect(database) as connection:
        await connection.execute(
            "UPDATE user_settings SET last_sources_json = 'broken' WHERE user_id = 12"
        )
        await connection.commit()

    assert await repository.get_sources(12) == []
