from __future__ import annotations

import gzip
import json
from pathlib import Path

from app.models import StickerKind
from app.services.errors import MediaValidationError

MAX_TGS_UNCOMPRESSED_BYTES = 5 * 1024 * 1024


def validate_sticker_file(path: Path, kind: StickerKind, max_bytes: int) -> None:
    size = path.stat().st_size
    if size <= 0 or size > max_bytes:
        raise MediaValidationError("Файл стикера пустой или слишком большой.")
    with path.open("rb") as source:
        header = source.read(16)
    if kind is StickerKind.STATIC:
        is_webp = header.startswith(b"RIFF") and header[8:12] == b"WEBP"
        is_png = header.startswith(b"\x89PNG\r\n\x1a\n")
        if not (is_webp or is_png):
            raise MediaValidationError("Ожидался статичный WEBP/PNG-стикер.")
    elif kind is StickerKind.VIDEO:
        if not header.startswith(b"\x1aE\xdf\xa3"):
            raise MediaValidationError("Ожидался WEBM-видеостикер.")
    elif kind is StickerKind.TGS:
        _validate_tgs(path)


def _validate_tgs(path: Path) -> None:
    try:
        with gzip.open(path, "rb") as compressed:
            payload = compressed.read(MAX_TGS_UNCOMPRESSED_BYTES + 1)
        if len(payload) > MAX_TGS_UNCOMPRESSED_BYTES:
            raise MediaValidationError("Распакованный TGS слишком большой.")
        data = json.loads(payload)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise MediaValidationError("Некорректный TGS-стикер.") from error
    required = {"v", "fr", "ip", "op", "w", "h", "layers"}
    if not isinstance(data, dict) or not required.issubset(data):
        raise MediaValidationError("TGS не содержит обязательных данных.")
