from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.bot.downloader import AiogramFileDownloader
from app.bot.handlers import router
from app.config import Settings, get_settings
from app.repositories import SettingsRepository
from app.services.conversion import ConversionService
from app.services.media_probe import MediaProbe
from app.services.media_renderer import MediaRenderer
from app.services.process_runner import ProcessRunner
from app.services.render_cache import RenderCache
from app.services.tgs_renderer import TgsRenderer


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def main() -> None:
    settings = get_settings()
    _configure_logging(settings)
    if settings.bot_token is None:
        raise RuntimeError("BOT_TOKEN is required")
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    repository = SettingsRepository(settings.database_path)
    await repository.initialize()
    runner = ProcessRunner()
    probe = MediaProbe(settings, runner)
    renderer = MediaRenderer(settings, runner, probe)
    conversion = ConversionService(
        settings,
        AiogramFileDownloader(bot),
        renderer,
        TgsRenderer(settings),
        probe,
        RenderCache(settings.cache_root, settings.max_cache_bytes),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Открыть конвертер"),
            BotCommand(command="cancel", description="Отменить ввод настройки"),
        ]
    )
    try:
        await dispatcher.start_polling(
            bot,
            repository=repository,
            conversion=conversion,
            app_settings=settings,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
