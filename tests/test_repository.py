from __future__ import annotations

from pathlib import Path

import pytest

from app.models import BackgroundKind, OutputFormat
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
        output_format=OutputFormat.FILE,
        emoji_size_percent=70,
    )
    await first.set_pending_action(42, "watermark")

    second = SettingsRepository(database)
    loaded = await second.get(42)
    assert defaults.background_color == "#F74539"
    assert updated.output_format is OutputFormat.FILE
    assert loaded.background_kind is BackgroundKind.PHOTO
    assert loaded.background_file_id == "photo-id"
    assert loaded.emoji_size_percent == 70
    assert await second.get_pending_action(42) == "watermark"


async def test_repository_rejects_unknown_update_field(tmp_path: Path) -> None:
    repository = SettingsRepository(tmp_path / "bot.sqlite3")
    await repository.initialize()

    with pytest.raises(ValueError):
        await repository.update(1, is_admin=True)
