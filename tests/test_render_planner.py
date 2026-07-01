from __future__ import annotations

import pytest

from app.models import BackgroundKind, UserSettings
from app.services.render_planner import build_layout, resolve_adaptive_color


def test_build_layout_keeps_single_emoji_even_sized() -> None:
    settings = UserSettings(user_id=1, emoji_size_percent=35)

    plan = build_layout(settings, 1)

    assert plan.columns == 1
    assert plan.rows == 1
    assert plan.cell_size == 184


def test_build_layout_fits_eight_assets_inside_canvas() -> None:
    settings = UserSettings(user_id=1, width=1280, height=720, emoji_size_percent=100)

    plan = build_layout(settings, 8)

    assert plan.columns == 4
    assert plan.rows == 2
    assert plan.cell_size * plan.columns <= settings.width
    assert plan.cell_size * plan.rows <= settings.height


@pytest.mark.parametrize("asset_count", [0, 9])
def test_build_layout_rejects_unsupported_asset_count(asset_count: int) -> None:
    with pytest.raises(ValueError):
        build_layout(UserSettings(user_id=1), asset_count)


@pytest.mark.parametrize(
    ("background", "expected"),
    [("#FFFFFF", "#000000"), ("#000000", "#FFFFFF"), ("#F74539", "#FFFFFF")],
)
def test_adaptive_color_contrasts_with_background(background: str, expected: str) -> None:
    settings = UserSettings(user_id=1, background_color=background)

    assert resolve_adaptive_color(settings) == expected


def test_adaptive_color_uses_white_for_media_and_honors_override() -> None:
    media = UserSettings(user_id=1, background_kind=BackgroundKind.VIDEO)
    override = UserSettings(user_id=1, emoji_color="#123456")

    assert resolve_adaptive_color(media) == "#FFFFFF"
    assert resolve_adaptive_color(override) == "#123456"
