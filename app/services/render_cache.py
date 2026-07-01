from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


class RenderCache:
    def __init__(self, root: Path, max_bytes: int) -> None:
        self._root = root
        self._max_bytes = max_bytes
        self._lock = asyncio.Lock()

    @staticmethod
    def key(**parts: Any) -> str:
        encoded = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    async def get(self, key: str, suffix: str) -> Path | None:
        path = self._root / f"{key}{suffix}"
        if not await asyncio.to_thread(path.is_file):
            return None
        await asyncio.to_thread(os.utime, path, None)
        return path

    async def put(self, source: Path, key: str, suffix: str) -> Path:
        async with self._lock:
            await asyncio.to_thread(self._root.mkdir, parents=True, exist_ok=True)
            destination = self._root / f"{key}{suffix}"
            temporary = self._root / f".{key}.tmp"
            await asyncio.to_thread(shutil.copyfile, source, temporary)
            await asyncio.to_thread(os.replace, temporary, destination)
            await self._prune()
            return destination

    async def _prune(self) -> None:
        entries = await asyncio.to_thread(self._cache_entries)
        total = sum(size for _, size in entries)
        for item, size in entries:
            if total <= self._max_bytes:
                break
            await asyncio.to_thread(item.unlink, missing_ok=True)
            total -= size

    def _cache_entries(self) -> list[tuple[Path, int]]:
        entries: list[tuple[Path, int, float]] = []
        for item in self._root.iterdir():
            if item.is_file() and not item.name.startswith("."):
                stat = item.stat()
                entries.append((item, stat.st_size, stat.st_mtime))
        entries.sort(key=lambda entry: entry[2])
        return [(path, size) for path, size, _ in entries]
