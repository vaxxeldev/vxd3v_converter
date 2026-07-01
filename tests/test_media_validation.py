from __future__ import annotations

from pathlib import Path

import pytest

from app.models import StickerKind
from app.services.errors import MediaValidationError
from app.services.media_validation import validate_sticker_file
from app.services.tgs_renderer import extract_tgs_json


def test_valid_tgs_is_parsed_without_changing_timing(tgs_file: Path, tmp_path: Path) -> None:
    destination = tmp_path / "sticker.json"

    validate_sticker_file(tgs_file, StickerKind.TGS, 1024 * 1024)
    metadata = extract_tgs_json(tgs_file, destination)

    assert metadata.width == 512
    assert metadata.height == 512
    assert metadata.fps == 60
    assert metadata.frame_count == 180
    assert metadata.duration_seconds == 3
    assert destination.read_bytes().startswith(b'{"v"')


@pytest.mark.parametrize(
    ("name", "content", "kind"),
    [
        ("bad.webp", b"not-webp", StickerKind.STATIC),
        ("bad.webm", b"not-webm", StickerKind.VIDEO),
        ("bad.tgs", b"not-gzip", StickerKind.TGS),
    ],
)
def test_invalid_sticker_signatures_are_rejected(
    tmp_path: Path,
    name: str,
    content: bytes,
    kind: StickerKind,
) -> None:
    path = tmp_path / name
    path.write_bytes(content)

    with pytest.raises(MediaValidationError):
        validate_sticker_file(path, kind, 1024)


def test_oversized_sticker_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "large.webp"
    path.write_bytes(b"RIFF" + b"0" * 20 + b"WEBP" + b"0" * 100)

    with pytest.raises(MediaValidationError, match="слишком большой"):
        validate_sticker_file(path, StickerKind.STATIC, 16)
