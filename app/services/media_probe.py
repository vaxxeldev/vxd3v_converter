from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from app.config import Settings
from app.services.errors import MediaValidationError
from app.services.process_runner import ProcessRunner


@dataclass(slots=True, frozen=True)
class VideoMetadata:
    codec: str
    profile: str | None
    width: int
    height: int
    pixel_format: str | None
    fps: float
    duration_seconds: float
    frame_count: int | None
    color_range: str | None = None
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None


class MediaProbe:
    def __init__(self, settings: Settings, runner: ProcessRunner) -> None:
        self._settings = settings
        self._runner = runner

    async def inspect(self, path: Path, *, count_frames: bool = False) -> VideoMetadata:
        entries = (
            "stream=codec_name,profile,width,height,pix_fmt,r_frame_rate,avg_frame_rate,"
            "nb_frames,nb_read_frames,color_range,color_space,color_transfer,color_primaries:"
            "format=duration"
        )
        command = [
            self._settings.ffprobe_bin,
            "-v",
            "error",
            "-select_streams",
            "v:0",
        ]
        if count_frames:
            command.append("-count_frames")
        command.extend(["-show_entries", entries, "-of", "json", str(path)])
        result = await self._runner.run(command, timeout_seconds=30)
        try:
            payload = json.loads(result.stdout)
            stream = payload["streams"][0]
            format_data = payload["format"]
            fps_value = stream.get("avg_frame_rate") or stream["r_frame_rate"]
            fps = float(Fraction(fps_value))
            frame_raw = stream.get("nb_read_frames") or stream.get("nb_frames")
            frame_count = int(frame_raw) if frame_raw not in {None, "N/A"} else None
            return VideoMetadata(
                codec=str(stream["codec_name"]),
                profile=str(stream["profile"]) if stream.get("profile") is not None else None,
                width=int(stream["width"]),
                height=int(stream["height"]),
                pixel_format=stream.get("pix_fmt"),
                fps=fps,
                duration_seconds=float(format_data["duration"]),
                frame_count=frame_count,
                color_range=stream.get("color_range"),
                color_space=stream.get("color_space"),
                color_transfer=stream.get("color_transfer"),
                color_primaries=stream.get("color_primaries"),
            )
        except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as error:
            raise MediaValidationError("Не удалось прочитать параметры видео.") from error

    async def verify_reference_contract(self, path: Path) -> VideoMetadata:
        metadata = await self.inspect(path, count_frames=True)
        if metadata.codec != "h264":
            raise MediaValidationError("Результат должен быть H.264.")
        if metadata.width != 1920 or metadata.height != 530:
            raise MediaValidationError("Результат не соответствует 1920×530.")
        if abs(metadata.fps - 60) > 0.01:
            raise MediaValidationError("Результат должен иметь 60 FPS.")
        if abs(metadata.duration_seconds - 3.0) > 0.02:
            raise MediaValidationError("Результат должен длиться три секунды.")
        if metadata.frame_count != 180:
            raise MediaValidationError("Результат должен содержать 180 кадров.")
        if metadata.pixel_format != "yuv420p":
            raise MediaValidationError("Результат должен использовать yuv420p.")
        if metadata.color_space != "bt709" or metadata.color_range not in {"tv", "limited"}:
            raise MediaValidationError("Результат должен использовать BT.709 limited.")
        return metadata

