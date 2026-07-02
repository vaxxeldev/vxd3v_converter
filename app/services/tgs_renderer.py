from __future__ import annotations

import asyncio
import gzip
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.services.errors import MediaValidationError, ProcessExecutionError
from app.services.process_runner import sanitize_stderr

logger = logging.getLogger(__name__)
MAX_TGS_JSON_BYTES = 5 * 1024 * 1024
MAX_TGS_FRAMES = 360
MAX_INTERMEDIATE_BYTES = 200 * 1024 * 1024


@dataclass(slots=True, frozen=True)
class TgsMetadata:
    width: int
    height: int
    fps: float
    frame_count: int

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.fps


def extract_tgs_json(source: Path, destination: Path) -> TgsMetadata:
    try:
        with gzip.open(source, "rb") as compressed:
            payload = compressed.read(MAX_TGS_JSON_BYTES + 1)
        if len(payload) > MAX_TGS_JSON_BYTES:
            raise MediaValidationError("Распакованный TGS слишком большой.")
        data: Any = json.loads(payload)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise MediaValidationError("Некорректный TGS-стикер.") from error
    if not isinstance(data, dict):
        raise MediaValidationError("Некорректная структура TGS.")
    try:
        width = int(data["w"])
        height = int(data["h"])
        fps = float(data["fr"])
        frame_count = math.ceil(float(data["op"]) - float(data["ip"]))
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise MediaValidationError("TGS не содержит корректные параметры анимации.") from error
    if not (1 <= width <= 512 and 1 <= height <= 512):
        raise MediaValidationError("Недопустимый размер холста TGS.")
    if not (0 < fps <= 60):
        raise MediaValidationError("Недопустимая частота кадров TGS.")
    if not (1 <= frame_count <= MAX_TGS_FRAMES):
        raise MediaValidationError("Недопустимая длительность TGS.")
    destination.write_bytes(payload)
    return TgsMetadata(width, height, fps, frame_count)


def _valid_intermediate(path: Path) -> bool:
    if not path.exists() or not 0 < path.stat().st_size <= MAX_INTERMEDIATE_BYTES:
        return False
    with path.open("rb") as media:
        return media.read(4) == b"\x1aE\xdf\xa3"


class TgsRenderer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def render(
        self,
        source: Path,
        destination: Path,
        *,
        width: int,
        height: int,
        tint: str | None = None,
    ) -> TgsMetadata:
        json_path = source.with_suffix(".json")
        metadata = await asyncio.to_thread(extract_tgs_json, source, json_path)
        try:
            await asyncio.wait_for(
                self._stream(json_path, destination, metadata, width, height, tint),
                timeout=self._settings.max_render_seconds,
            )
        except TimeoutError as error:
            raise ProcessExecutionError("Превышено время рендера TGS.") from error
        if not await asyncio.to_thread(_valid_intermediate, destination):
            raise MediaValidationError("Не удалось создать lossless-анимацию из TGS.")
        return metadata

    async def _stream(
        self,
        json_path: Path,
        destination: Path,
        metadata: TgsMetadata,
        width: int,
        height: int,
        tint: str | None,
    ) -> None:
        renderer = await asyncio.create_subprocess_exec(
            self._settings.rlottie_renderer_bin,
            str(json_path),
            str(width),
            str(height),
            tint or "none",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        encoder = await asyncio.create_subprocess_exec(
            self._settings.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            "bgra",
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            f"{metadata.fps:g}",
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-pix_fmt",
            "bgra",
            str(destination),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        renderer_stderr_task = asyncio.create_task(renderer.stderr.read())
        encoder_stderr_task = asyncio.create_task(encoder.stderr.read())
        try:
            if renderer.stdout is None or encoder.stdin is None:
                raise ProcessExecutionError("Не удалось создать поток TGS.")
            while chunk := await renderer.stdout.read(1024 * 1024):
                encoder.stdin.write(chunk)
                await encoder.stdin.drain()
            encoder.stdin.close()
            await encoder.stdin.wait_closed()
            renderer_code, encoder_code = await asyncio.gather(renderer.wait(), encoder.wait())
            renderer_stderr, encoder_stderr = await asyncio.gather(
                renderer_stderr_task,
                encoder_stderr_task,
            )
        except BaseException:
            for process in (renderer, encoder):
                if process.returncode is None:
                    process.kill()
            await asyncio.gather(renderer.wait(), encoder.wait(), return_exceptions=True)
            renderer_stderr_task.cancel()
            encoder_stderr_task.cancel()
            raise
        if renderer_code != 0 or encoder_code != 0:
            logger.error(
                "TGS pipeline failed renderer=%s encoder=%s renderer_stderr=%s encoder_stderr=%s",
                renderer_code,
                encoder_code,
                sanitize_stderr(renderer_stderr),
                sanitize_stderr(encoder_stderr),
            )
            raise ProcessExecutionError("Не удалось отрисовать TGS-анимацию.")
