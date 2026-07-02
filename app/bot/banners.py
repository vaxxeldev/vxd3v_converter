from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path

from aiogram.types import FSInputFile

from app.config import Settings
from app.repositories import SettingsRepository
from app.services.errors import MediaValidationError

_BANNER_FILES = {
    "start": "старт.mp4",
    "wallet": "кошелёк.mp4",
    "topup": "начисление баланса.mp4",
    "size": "размеры.mp4",
    "resolution": "смена разрешения.mp4",
    "preview": "предпросмотр.mp4",
}
_MAX_BANNER_BYTES = 10 * 1024 * 1024


@dataclass(slots=True, frozen=True)
class BannerMedia:
    key: str
    sha256: str
    media: str | FSInputFile
    cached: bool


class BannerService:
    def __init__(self, settings: Settings, repository: SettingsRepository) -> None:
        self._root = settings.banner_root
        self._repository = repository
        self._memory: dict[str, tuple[str, str]] = {}
        self._lock = asyncio.Lock()

    async def resolve(self, key: str) -> BannerMedia:
        path = self.path_for(key)
        sha256 = await asyncio.to_thread(self._validate_and_hash, path)
        async with self._lock:
            memory = self._memory.get(key)
            if memory and memory[0] == sha256:
                return BannerMedia(key, sha256, memory[1], True)
            stored = await self._repository.get_banner_cache(key)
            if stored and stored[0] == sha256:
                self._memory[key] = stored
                return BannerMedia(key, sha256, stored[1], True)
            if stored:
                await self._repository.delete_banner_cache(key)
            self._memory.pop(key, None)
        return BannerMedia(key, sha256, FSInputFile(path), False)

    async def remember(self, media: BannerMedia, file_id: str) -> None:
        async with self._lock:
            self._memory[media.key] = (media.sha256, file_id)
            await self._repository.set_banner_cache(media.key, media.sha256, file_id)

    async def invalidate(self, key: str) -> None:
        async with self._lock:
            self._memory.pop(key, None)
            await self._repository.delete_banner_cache(key)

    def path_for(self, key: str) -> Path:
        try:
            filename = _BANNER_FILES[key]
        except KeyError as error:
            raise MediaValidationError("Неизвестный баннер интерфейса.") from error
        return self._root / filename

    @staticmethod
    def _validate_and_hash(path: Path) -> str:
        if not path.is_file():
            raise MediaValidationError("Баннер интерфейса не найден.")
        size = path.stat().st_size
        if not 0 < size <= _MAX_BANNER_BYTES:
            raise MediaValidationError("Некорректный размер баннера интерфейса.")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
