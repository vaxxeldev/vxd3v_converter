from __future__ import annotations

from pathlib import Path

from app.services.render_cache import RenderCache


async def test_cache_key_is_deterministic() -> None:
    assert RenderCache.key(size=128, tint=None) == RenderCache.key(tint=None, size=128)
    assert RenderCache.key(size=128) != RenderCache.key(size=256)


async def test_cache_prunes_oldest_files(tmp_path: Path) -> None:
    source_a = tmp_path / "a.source"
    source_b = tmp_path / "b.source"
    source_a.write_bytes(b"a" * 8)
    source_b.write_bytes(b"b" * 8)
    cache = RenderCache(tmp_path / "cache", max_bytes=8)

    first = await cache.put(source_a, "first", ".mkv")
    second = await cache.put(source_b, "second", ".mkv")

    assert not first.exists()
    assert second.read_bytes() == b"b" * 8
