from __future__ import annotations

from pathlib import Path

from aiogram import Bot


class AiogramFileDownloader:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def download_file(self, file_id: str, destination: Path) -> None:
        await self._bot.download(file_id, destination=destination)
