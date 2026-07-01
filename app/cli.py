from __future__ import annotations

import argparse
import asyncio
import shutil
import tempfile
from pathlib import Path

from app.config import Settings
from app.models import (
    LocalAsset,
    LocalTrack,
    OutputFormat,
    RenderRequest,
    StickerKind,
    UserSettings,
)
from app.services.media_probe import MediaProbe
from app.services.media_renderer import MediaRenderer
from app.services.media_validation import validate_sticker_file
from app.services.process_runner import ProcessRunner
from app.services.render_planner import build_layout
from app.services.tgs_renderer import TgsRenderer


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a sticker without Telegram")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--background", default="#F74539")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=530)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--size", type=int, default=35)
    parser.add_argument("--format", choices=[item.value for item in OutputFormat], default="file")
    return parser.parse_args()


def _kind(path: Path) -> StickerKind:
    suffix = path.suffix.lower()
    if suffix == ".tgs":
        return StickerKind.TGS
    if suffix == ".webm":
        return StickerKind.VIDEO
    if suffix in {".webp", ".png"}:
        return StickerKind.STATIC
    raise ValueError("source must be .tgs, .webm, .webp or .png")


async def _render(arguments: argparse.Namespace) -> None:
    app_settings = Settings()
    runner = ProcessRunner()
    probe = MediaProbe(app_settings, runner)
    renderer = MediaRenderer(app_settings, runner, probe)
    user_settings = UserSettings(
        user_id=0,
        background_color=arguments.background.upper(),
        width=arguments.width,
        height=arguments.height,
        fps=arguments.fps,
        emoji_size_percent=arguments.size,
        output_format=OutputFormat(arguments.format),
    )
    kind = _kind(arguments.source)
    validate_sticker_file(arguments.source, kind, app_settings.max_input_bytes)
    with tempfile.TemporaryDirectory(prefix="vxd3v-cli-") as directory:
        working = Path(directory)
        if kind is StickerKind.TGS:
            size = build_layout(user_settings, 1).cell_size
            intermediate = working / "source.mkv"
            metadata = await TgsRenderer(app_settings).render(
                arguments.source,
                intermediate,
                width=size,
                height=size,
            )
            track = LocalTrack(intermediate, kind, metadata.fps, metadata.duration_seconds)
        elif kind is StickerKind.VIDEO:
            metadata = await probe.inspect(arguments.source)
            track = LocalTrack(arguments.source, kind, metadata.fps, metadata.duration_seconds)
        else:
            track = LocalTrack(arguments.source, kind, 60.0, 3.0)
        temporary_output = working / arguments.output.name
        result = await renderer.render(
            RenderRequest(
                settings=user_settings,
                assets=[LocalAsset(track)],
                output_path=temporary_output,
            )
        )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, temporary_output, arguments.output)
        print(
            f"Rendered {arguments.output}: {result.width}x{result.height}, "
            f"{result.fps:g} FPS, {result.frame_count or '?'} frames"
        )


def run() -> None:
    asyncio.run(_render(_arguments()))


if __name__ == "__main__":
    run()
