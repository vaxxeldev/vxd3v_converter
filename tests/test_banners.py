from __future__ import annotations

from pathlib import Path

from aiogram.types import FSInputFile

from app.bot.banners import BannerService
from app.config import Settings
from app.repositories import SettingsRepository


async def test_banner_file_id_is_reused_from_persistent_cache(tmp_path: Path) -> None:
    root = tmp_path / "banners"
    root.mkdir()
    (root / "старт.mp4").write_bytes(b"first-banner")
    repository = SettingsRepository(tmp_path / "bot.sqlite3")
    await repository.initialize()
    settings = Settings(banner_root=root)
    first_service = BannerService(settings, repository)

    first = await first_service.resolve("start")
    await first_service.remember(first, "telegram-file-id")
    second_service = BannerService(settings, repository)
    second = await second_service.resolve("start")

    assert isinstance(first.media, FSInputFile)
    assert second.media == "telegram-file-id"
    assert second.cached is True


async def test_changed_banner_invalidates_cached_file_id(tmp_path: Path) -> None:
    root = tmp_path / "banners"
    root.mkdir()
    path = root / "старт.mp4"
    path.write_bytes(b"first-banner")
    repository = SettingsRepository(tmp_path / "bot.sqlite3")
    await repository.initialize()
    service = BannerService(Settings(banner_root=root), repository)
    first = await service.resolve("start")
    await service.remember(first, "old-file-id")

    path.write_bytes(b"updated-banner")
    updated = await service.resolve("start")

    assert isinstance(updated.media, FSInputFile)
    assert updated.cached is False
    assert updated.sha256 != first.sha256
    assert await repository.get_banner_cache("start") is None
