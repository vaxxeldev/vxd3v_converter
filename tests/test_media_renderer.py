from __future__ import annotations

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
from app.services.process_runner import ProcessRunner


def _renderer() -> MediaRenderer:
    settings = Settings()
    runner = ProcessRunner()
    return MediaRenderer(settings, runner, MediaProbe(settings, runner))


def test_h264_command_matches_reference_contract(tmp_path: Path) -> None:
    source = tmp_path / "source.mkv"
    request = RenderRequest(
        settings=UserSettings(user_id=1, output_format=OutputFormat.ANIMATION),
        assets=[LocalAsset(LocalTrack(source, StickerKind.TGS, 60, 3))],
        output_path=tmp_path / "result.mp4",
    )

    command = _renderer().build_command(request)
    graph = command[command.index("-filter_complex") + 1]

    assert command[command.index("-frames:v") + 1] == "180"
    assert command[command.index("-r") + 1] == "60"
    assert command[command.index("-profile:v") + 1] == "high"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-colorspace") + 1] == "bt709"
    assert "transfer=bt709" in command[command.index("-x264-params") + 1]
    assert "scale=184:184" in graph
    assert "overlay=(W-w)/2:(H-h)/2" in graph


def test_gif_command_uses_two_pass_palette(tmp_path: Path) -> None:
    request = RenderRequest(
        settings=UserSettings(user_id=1, output_format=OutputFormat.GIF),
        assets=[LocalAsset(LocalTrack(tmp_path / "source.webp", StickerKind.STATIC, 60, 3))],
        output_path=tmp_path / "result.gif",
    )

    command = _renderer().build_command(request)
    graph = command[command.index("-filter_complex") + 1]

    assert "palettegen" in graph
    assert "paletteuse" in graph
    assert "libx264" not in command


def test_premium_effect_is_composited_before_centering(tmp_path: Path) -> None:
    main = LocalTrack(tmp_path / "main.mkv", StickerKind.TGS, 60, 3)
    effect = LocalTrack(tmp_path / "effect.mkv", StickerKind.TGS, 60, 3)
    request = RenderRequest(
        settings=UserSettings(user_id=1),
        assets=[LocalAsset(main, effect)],
        output_path=tmp_path / "result.mp4",
    )

    command = _renderer().build_command(request)
    graph = command[command.index("-filter_complex") + 1]

    assert "[main0][effect0]overlay=0:0:shortest=1[asset0]" in graph
    assert "[base][asset0]overlay=(W-w)/2:(H-h)/2" in graph
