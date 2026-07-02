from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class OutputFormat(StrEnum):
    ANIMATION = "animation"
    VIDEO = "video"
    FILE = "file"
    GIF = "gif"


class BackgroundKind(StrEnum):
    COLOR = "color"
    PHOTO = "photo"
    VIDEO = "video"
    ANIMATION = "animation"


class WatermarkPosition(StrEnum):
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    CENTER = "center"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


class StickerKind(StrEnum):
    STATIC = "static"
    TGS = "tgs"
    VIDEO = "video"


@dataclass(slots=True)
class UserSettings:
    user_id: int
    balance_kopecks: int = 0
    background_kind: BackgroundKind = BackgroundKind.COLOR
    background_color: str = "#F74539"
    background_file_id: str | None = None
    width: int = 1920
    height: int = 530
    fps: int = 60
    output_format: OutputFormat = OutputFormat.ANIMATION
    emoji_size_percent: int = 35
    emoji_color: str | None = None
    watermark_text: str | None = None
    watermark_position: WatermarkPosition = WatermarkPosition.BOTTOM_RIGHT
    watermark_font_scale: float = 0.04


@dataclass(slots=True, frozen=True)
class SourceAsset:
    file_id: str
    file_unique_id: str
    kind: StickerKind
    emoji: str | None = None
    custom_emoji_id: str | None = None
    needs_repainting: bool = False
    premium_animation_file_id: str | None = None


@dataclass(slots=True, frozen=True)
class LocalTrack:
    path: Path
    kind: StickerKind
    fps: float
    duration_seconds: float


@dataclass(slots=True, frozen=True)
class LocalAsset:
    main: LocalTrack
    effect: LocalTrack | None = None
    needs_repainting: bool = False


@dataclass(slots=True)
class RenderRequest:
    settings: UserSettings
    assets: list[LocalAsset]
    background_path: Path | None = None
    duration_seconds: float = 3.0
    output_path: Path = field(default_factory=lambda: Path("result.mp4"))
