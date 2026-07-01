from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.models import (
    BackgroundKind,
    LocalAsset,
    LocalTrack,
    OutputFormat,
    RenderRequest,
    SourceAsset,
    StickerKind,
    UserSettings,
)
from app.services.errors import ConversionBusyError, MediaValidationError, QueueFullError
from app.services.media_probe import MediaProbe, VideoMetadata
from app.services.media_renderer import MediaRenderer
from app.services.media_validation import validate_sticker_file
from app.services.render_cache import RenderCache
from app.services.render_planner import build_layout, resolve_adaptive_color
from app.services.tgs_renderer import TgsRenderer


class TelegramFileDownloader(Protocol):
    async def download_file(self, file_id: str, destination: Path) -> None: ...


@dataclass(slots=True, frozen=True)
class RenderedMedia:
    path: Path
    metadata: VideoMetadata
    output_format: OutputFormat


class RenderGate:
    """Bound concurrent work and reject duplicate jobs from the same user."""

    def __init__(self, concurrent: int, queue_size: int) -> None:
        self._semaphore = asyncio.Semaphore(concurrent)
        self._capacity = concurrent + queue_size
        self._lock = asyncio.Lock()
        self._active_users: set[int] = set()
        self._job_count = 0

    @asynccontextmanager
    async def acquire(self, user_id: int) -> AsyncIterator[None]:
        async with self._lock:
            if user_id in self._active_users:
                raise ConversionBusyError("Дождись завершения текущей конвертации.")
            if self._job_count >= self._capacity:
                raise QueueFullError("Очередь заполнена. Попробуй ещё раз через минуту.")
            self._active_users.add(user_id)
            self._job_count += 1
        try:
            async with self._semaphore:
                yield
        finally:
            async with self._lock:
                self._active_users.discard(user_id)
                self._job_count -= 1


class ConversionService:
    def __init__(
        self,
        settings: Settings,
        downloader: TelegramFileDownloader,
        renderer: MediaRenderer,
        tgs_renderer: TgsRenderer,
        probe: MediaProbe,
        cache: RenderCache,
    ) -> None:
        self._settings = settings
        self._downloader = downloader
        self._renderer = renderer
        self._tgs_renderer = tgs_renderer
        self._probe = probe
        self._cache = cache
        self._gate = RenderGate(settings.max_concurrent_renders, settings.max_queue_size)

    @asynccontextmanager
    async def convert(
        self,
        user_settings: UserSettings,
        sources: list[SourceAsset],
    ) -> AsyncIterator[RenderedMedia]:
        if not 1 <= len(sources) <= 8:
            raise MediaValidationError("Отправь от одного до восьми эмодзи или стикеров.")
        render_dir = self._settings.temp_root / f"render-{user_settings.user_id}-{uuid.uuid4().hex}"
        await asyncio.to_thread(render_dir.mkdir, parents=True, exist_ok=False)
        try:
            async with self._gate.acquire(user_settings.user_id):
                assets = await self._prepare_assets(user_settings, sources, render_dir)
                background = await self._prepare_background(user_settings, render_dir)
                output_suffix = (
                    ".gif" if user_settings.output_format is OutputFormat.GIF else ".mp4"
                )
                output = render_dir / f"result{output_suffix}"
                request = RenderRequest(
                    settings=user_settings,
                    assets=assets,
                    background_path=background,
                    duration_seconds=3.0,
                    output_path=output,
                )
                metadata = await self._renderer.render(request)
                yield RenderedMedia(output, metadata, user_settings.output_format)
        finally:
            await asyncio.to_thread(shutil.rmtree, render_dir, ignore_errors=True)

    async def _prepare_assets(
        self,
        settings: UserSettings,
        sources: list[SourceAsset],
        render_dir: Path,
    ) -> list[LocalAsset]:
        plan = build_layout(settings, len(sources))
        assets: list[LocalAsset] = []
        for index, source in enumerate(sources):
            source_path = render_dir / f"source-{index}{self._source_suffix(source.kind)}"
            await self._downloader.download_file(source.file_id, source_path)
            await asyncio.to_thread(
                validate_sticker_file,
                source_path,
                source.kind,
                self._settings.max_input_bytes,
            )
            main, repaint_in_compositor = await self._prepare_track(
                source_path,
                source,
                plan.cell_size,
                render_dir,
                index,
                settings,
            )
            effect = await self._prepare_effect(source, plan.cell_size, render_dir, index)
            assets.append(LocalAsset(main, effect, repaint_in_compositor))
        return assets

    async def _prepare_track(
        self,
        source_path: Path,
        source: SourceAsset,
        size: int,
        render_dir: Path,
        index: int,
        settings: UserSettings,
    ) -> tuple[LocalTrack, bool]:
        if source.kind is StickerKind.TGS:
            tint = resolve_adaptive_color(settings) if source.needs_repainting else None
            track = await self._render_tgs_cached(
                source_path,
                source.file_unique_id,
                size,
                tint,
                render_dir / f"main-{index}.mkv",
            )
            return track, False
        if source.kind is StickerKind.VIDEO:
            metadata = await self._probe.inspect(source_path)
            self._validate_video_sticker(metadata)
            return (
                LocalTrack(source_path, StickerKind.VIDEO, metadata.fps, metadata.duration_seconds),
                source.needs_repainting,
            )
        return LocalTrack(source_path, StickerKind.STATIC, 60.0, 3.0), source.needs_repainting

    async def _prepare_effect(
        self,
        source: SourceAsset,
        size: int,
        render_dir: Path,
        index: int,
    ) -> LocalTrack | None:
        if not source.premium_animation_file_id:
            return None
        effect_path = render_dir / f"effect-{index}.tgs"
        await self._downloader.download_file(source.premium_animation_file_id, effect_path)
        await asyncio.to_thread(
            validate_sticker_file,
            effect_path,
            StickerKind.TGS,
            self._settings.max_input_bytes,
        )
        return await self._render_tgs_cached(
            effect_path,
            f"premium:{source.premium_animation_file_id}",
            size,
            None,
            render_dir / f"effect-{index}.mkv",
        )

    async def _render_tgs_cached(
        self,
        source: Path,
        unique_id: str,
        size: int,
        tint: str | None,
        destination: Path,
    ) -> LocalTrack:
        cache_key = self._cache.key(kind="tgs", unique_id=unique_id, size=size, tint=tint)
        cached = await self._cache.get(cache_key, ".mkv")
        if cached is None:
            metadata = await self._tgs_renderer.render(
                source,
                destination,
                width=size,
                height=size,
                tint=tint,
            )
            cached = await self._cache.put(destination, cache_key, ".mkv")
            return LocalTrack(cached, StickerKind.TGS, metadata.fps, metadata.duration_seconds)
        metadata = await self._probe.inspect(cached)
        return LocalTrack(cached, StickerKind.TGS, metadata.fps, metadata.duration_seconds)

    async def _prepare_background(
        self,
        settings: UserSettings,
        render_dir: Path,
    ) -> Path | None:
        if settings.background_kind is BackgroundKind.COLOR:
            return None
        if not settings.background_file_id:
            raise MediaValidationError("Сначала отправь своё медиа для фона.")
        suffix = ".jpg" if settings.background_kind is BackgroundKind.PHOTO else ".mp4"
        destination = render_dir / f"background{suffix}"
        await self._downloader.download_file(settings.background_file_id, destination)
        size = await asyncio.to_thread(lambda: destination.stat().st_size)
        if not 0 < size <= self._settings.max_input_bytes:
            raise MediaValidationError("Фоновое медиа пустое или слишком большое.")
        if settings.background_kind is not BackgroundKind.PHOTO:
            metadata = await self._probe.inspect(destination)
            if metadata.width < 2 or metadata.height < 2 or metadata.duration_seconds <= 0:
                raise MediaValidationError("Некорректное видео для фона.")
        return destination

    @staticmethod
    def _source_suffix(kind: StickerKind) -> str:
        return {
            StickerKind.STATIC: ".webp",
            StickerKind.TGS: ".tgs",
            StickerKind.VIDEO: ".webm",
        }[kind]

    @staticmethod
    def _validate_video_sticker(metadata: VideoMetadata) -> None:
        if metadata.codec not in {"vp9", "vp8"}:
            raise MediaValidationError("Видео-стикер должен использовать VP9 или VP8.")
        if metadata.width > 512 or metadata.height > 512:
            raise MediaValidationError("Видео-стикер превышает 512×512.")
        if not 0 < metadata.duration_seconds <= 3.1:
            raise MediaValidationError("Видео-стикер должен длиться не более трёх секунд.")
        if not 0 < metadata.fps <= 60.1:
            raise MediaValidationError("Некорректная частота кадров видео-стикера.")
