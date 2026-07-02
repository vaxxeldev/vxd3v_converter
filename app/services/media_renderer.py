from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.models import (
    BackgroundKind,
    LocalAsset,
    LocalTrack,
    OutputFormat,
    RenderRequest,
    StickerKind,
    WatermarkFont,
)
from app.services.errors import MediaValidationError
from app.services.media_probe import MediaProbe, VideoMetadata
from app.services.process_runner import ProcessRunner
from app.services.render_planner import build_layout, resolve_adaptive_color


@dataclass(slots=True, frozen=True)
class InputAsset:
    main_index: int
    effect_index: int | None
    asset: LocalAsset


class MediaRenderer:
    def __init__(
        self,
        settings: Settings,
        runner: ProcessRunner,
        probe: MediaProbe,
    ) -> None:
        self._settings = settings
        self._runner = runner
        self._probe = probe

    async def render(self, request: RenderRequest) -> VideoMetadata:
        command = self.build_command(request)
        await self._runner.run(
            command,
            timeout_seconds=self._settings.max_render_seconds,
            cwd=request.output_path.parent,
        )
        if not await asyncio.to_thread(request.output_path.is_file):
            raise MediaValidationError("Результирующий файл не создан.")
        size = await asyncio.to_thread(lambda: request.output_path.stat().st_size)
        if size <= 0 or size > self._settings.max_output_bytes:
            await asyncio.to_thread(request.output_path.unlink, missing_ok=True)
            raise MediaValidationError("Результат слишком большой для отправки.")
        return await self._probe.inspect(request.output_path, count_frames=True)

    def build_command(self, request: RenderRequest) -> list[str]:
        settings = request.settings
        command = [
            self._settings.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
        ]
        if request.background_path:
            if settings.background_kind is BackgroundKind.PHOTO:
                command.extend(["-loop", "1"])
            else:
                command.extend(["-stream_loop", "-1"])
            command.extend(["-i", str(request.background_path)])
        else:
            color = settings.background_color.removeprefix("#")
            command.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=0x{color}:s={settings.width}x{settings.height}:"
                    f"r={settings.fps}:d={request.duration_seconds:.6f}",
                ]
            )

        indexed_assets: list[InputAsset] = []
        next_index = 1
        for asset in request.assets:
            command.extend(self._input_arguments(asset.main))
            main_index = next_index
            next_index += 1
            effect_index: int | None = None
            if asset.effect:
                command.extend(self._input_arguments(asset.effect))
                effect_index = next_index
                next_index += 1
            indexed_assets.append(InputAsset(main_index, effect_index, asset))

        filter_graph, output_label = self._build_filter_graph(request, indexed_assets)
        command.extend(["-filter_complex", filter_graph, "-map", f"[{output_label}]", "-an"])
        frame_count = max(1, round(request.duration_seconds * settings.fps))
        command.extend(["-frames:v", str(frame_count), "-r", str(settings.fps)])
        if settings.output_format is OutputFormat.GIF:
            command.extend(["-loop", "0", str(request.output_path)])
        else:
            crf = "12" if settings.output_format is OutputFormat.FILE else "15"
            command.extend(
                [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "slow",
                    "-tune",
                    "animation",
                    "-crf",
                    crf,
                    "-profile:v",
                    "high",
                    "-level:v",
                    "5.1",
                    "-pix_fmt",
                    "yuv420p",
                    "-color_range",
                    "tv",
                    "-colorspace",
                    "bt709",
                    "-color_primaries:v",
                    "bt709",
                    "-color_trc:v",
                    "bt709",
                    "-x264-params",
                    "colorprim=bt709:transfer=bt709:colormatrix=bt709:fullrange=off",
                    "-movflags",
                    "+faststart",
                    str(request.output_path),
                ]
            )
        return command

    @staticmethod
    def _input_arguments(track: LocalTrack) -> list[str]:
        if track.kind is StickerKind.STATIC:
            return ["-loop", "1", "-i", str(track.path)]
        return ["-stream_loop", "-1", "-i", str(track.path)]

    def _build_filter_graph(
        self,
        request: RenderRequest,
        indexed_assets: list[InputAsset],
    ) -> tuple[str, str]:
        settings = request.settings
        width, height, fps = settings.width, settings.height, settings.fps
        plan = build_layout(settings, len(indexed_assets))
        filters = [
            f"[0:v]fps={fps},scale={width}:{height}:force_original_aspect_ratio=increase:"
            "flags=lanczos+accurate_rnd+full_chroma_int,"
            f"crop={width}:{height},setsar=1,format=rgba[base]"
        ]
        tint = resolve_adaptive_color(settings)
        asset_labels: list[str] = []
        for position, indexed in enumerate(indexed_assets):
            main_label = f"main{position}"
            filters.append(
                self._track_filter(
                    indexed.main_index,
                    main_label,
                    plan.cell_size,
                    fps,
                    tint if indexed.asset.needs_repainting else None,
                )
            )
            if indexed.effect_index is not None:
                effect_label = f"effect{position}"
                filters.append(
                    self._track_filter(
                        indexed.effect_index,
                        effect_label,
                        plan.cell_size,
                        fps,
                        None,
                    )
                )
                combined = f"asset{position}"
                filters.append(f"[{main_label}][{effect_label}]overlay=0:0:shortest=1[{combined}]")
                asset_labels.append(combined)
            else:
                asset_labels.append(main_label)

        if len(asset_labels) == 1:
            group_label = asset_labels[0]
        else:
            layout = "|".join(
                f"{(index % plan.columns) * plan.cell_size}_"
                f"{(index // plan.columns) * plan.cell_size}"
                for index in range(len(asset_labels))
            )
            inputs = "".join(f"[{label}]" for label in asset_labels)
            filters.append(
                f"{inputs}xstack=inputs={len(asset_labels)}:layout={layout}:fill=black@0[group]"
            )
            group_label = "group"

        filters.append(f"[base][{group_label}]overlay=(W-w)/2:(H-h)/2:shortest=1[scene]")
        current = "scene"
        if settings.watermark_text:
            text_path = request.output_path.parent / "watermark.txt"
            text_path.write_text(settings.watermark_text, encoding="utf-8")
            x, y = self._watermark_coordinates(settings.watermark_position.value)
            font_size = max(12, int(height * settings.watermark_font_scale))
            font_file = {
                WatermarkFont.MONTSERRAT: self._settings.montserrat_font_file,
                WatermarkFont.SPACE_MONO: self._settings.space_mono_font_file,
            }[settings.watermark_font]
            filters.append(
                f"[{current}]drawtext=fontfile='{self._escape_path(font_file)}':"
                f"textfile='{self._escape_path(text_path)}':fontcolor=white@0.78:"
                f"fontsize={font_size}:borderw=1:bordercolor=black@0.45:"
                f"x={x}:y={y}[watermarked]"
            )
            current = "watermarked"

        duration = f"{request.duration_seconds:.6f}"
        if settings.output_format is OutputFormat.GIF:
            filters.append(
                f"[{current}]trim=duration={duration},setpts=PTS-STARTPTS[trimmed];"
                "[trimmed]split[gif_a][gif_b];"
                "[gif_a]palettegen=stats_mode=diff:reserve_transparent=0[palette];"
                "[gif_b][palette]paletteuse=dither=sierra2_4a[output]"
            )
        else:
            filters.append(
                f"[{current}]trim=duration={duration},setpts=PTS-STARTPTS,format=yuv420p[output]"
            )
        return ";".join(filters), "output"

    @staticmethod
    def _track_filter(
        input_index: int,
        label: str,
        cell_size: int,
        fps: int,
        tint: str | None,
    ) -> str:
        chain = (
            f"[{input_index}:v]fps={fps},setpts=PTS-STARTPTS,"
            f"scale={cell_size}:{cell_size}:force_original_aspect_ratio=decrease:"
            "flags=lanczos+accurate_rnd+full_chroma_int,"
            f"pad={cell_size}:{cell_size}:(ow-iw)/2:(oh-ih)/2:color=black@0,format=rgba"
        )
        if tint:
            red, green, blue = MediaRenderer._hex_channels(tint)
            chain += f",lutrgb=r={red}:g={green}:b={blue}"
        return f"{chain}[{label}]"

    @staticmethod
    def _hex_channels(color: str) -> tuple[int, int, int]:
        value = color.removeprefix("#")
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)

    @staticmethod
    def _watermark_coordinates(position: str) -> tuple[str, str]:
        margin = "20"
        return {
            "top_left": (margin, margin),
            "top_right": (f"w-tw-{margin}", margin),
            "center": ("(w-tw)/2", "(h-th)/2"),
            "bottom_left": (margin, f"h-th-{margin}"),
            "bottom_right": (f"w-tw-{margin}", f"h-th-{margin}"),
        }[position]

    @staticmethod
    def _escape_path(path: Path) -> str:
        return str(path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
