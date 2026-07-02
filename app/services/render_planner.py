from __future__ import annotations

import math
from dataclasses import dataclass

from app.models import BackgroundKind, UserSettings


@dataclass(slots=True, frozen=True)
class LayoutPlan:
    columns: int
    rows: int
    cell_size: int


def build_layout(settings: UserSettings, asset_count: int) -> LayoutPlan:
    if not 1 <= asset_count <= 8:
        raise ValueError("asset_count must be between 1 and 8")
    columns = min(4, asset_count)
    rows = math.ceil(asset_count / columns)
    target = min(settings.width, settings.height) * settings.emoji_size_percent / 100
    cell = int(
        min(
            target,
            settings.width * 0.92 / columns,
            settings.height * 0.92 / rows,
            2160,
        )
    )
    cell = max(2, cell - cell % 2)
    return LayoutPlan(columns, rows, cell)


def resolve_adaptive_color(settings: UserSettings) -> str:
    if settings.emoji_color:
        return settings.emoji_color
    if settings.background_kind is not BackgroundKind.COLOR:
        return "#FFFFFF"
    color = settings.background_color.removeprefix("#")
    red, green, blue = (int(color[index : index + 2], 16) for index in (0, 2, 4))
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    return "#000000" if luminance > 0.5 else "#FFFFFF"
