from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiosqlite

from app.models import (
    BackgroundKind,
    OutputFormat,
    SourceAsset,
    StickerKind,
    UserSettings,
    WatermarkFont,
    WatermarkPosition,
)

_UPDATABLE_FIELDS = {
    "background_kind",
    "background_color",
    "background_file_id",
    "width",
    "height",
    "fps",
    "emoji_size_percent",
    "emoji_color",
    "watermark_text",
    "watermark_position",
    "watermark_font",
}


class SettingsRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    async def initialize(self) -> None:
        await asyncio.to_thread(self._database_path.parent.mkdir, parents=True, exist_ok=True)
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    balance_kopecks INTEGER NOT NULL DEFAULT 0 CHECK(balance_kopecks >= 0),
                    background_kind TEXT NOT NULL DEFAULT 'color',
                    background_color TEXT NOT NULL DEFAULT '#F74539',
                    background_file_id TEXT,
                    width INTEGER NOT NULL DEFAULT 1920,
                    height INTEGER NOT NULL DEFAULT 530,
                    fps INTEGER NOT NULL DEFAULT 60,
                    output_format TEXT NOT NULL DEFAULT 'animation',
                    emoji_size_percent INTEGER NOT NULL DEFAULT 35,
                    emoji_color TEXT,
                    watermark_text TEXT,
                    watermark_position TEXT NOT NULL DEFAULT 'bottom_right',
                    pending_action TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS banner_cache (
                    banner_key TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                UPDATE user_settings
                SET output_format = 'animation'
                WHERE output_format <> 'animation';
                """
            )
            await self._ensure_ui_columns(connection)
            await connection.commit()

    @staticmethod
    async def _ensure_ui_columns(connection: aiosqlite.Connection) -> None:
        cursor = await connection.execute("PRAGMA table_info(user_settings)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "panel_chat_id" not in columns:
            await connection.execute("ALTER TABLE user_settings ADD COLUMN panel_chat_id INTEGER")
        if "panel_message_id" not in columns:
            await connection.execute(
                "ALTER TABLE user_settings ADD COLUMN panel_message_id INTEGER"
            )
        if "preview_message_id" not in columns:
            await connection.execute(
                "ALTER TABLE user_settings ADD COLUMN preview_message_id INTEGER"
            )
        if "last_sources_json" not in columns:
            await connection.execute(
                "ALTER TABLE user_settings ADD COLUMN last_sources_json TEXT"
            )
        if "panel_banner" not in columns:
            await connection.execute(
                "ALTER TABLE user_settings ADD COLUMN panel_banner TEXT"
            )
        if "username" not in columns:
            await connection.execute("ALTER TABLE user_settings ADD COLUMN username TEXT")
            await connection.execute(
                "CREATE INDEX IF NOT EXISTS user_settings_username ON user_settings(username)"
            )
        if "watermark_font" not in columns:
            await connection.execute(
                "ALTER TABLE user_settings ADD COLUMN watermark_font TEXT "
                "NOT NULL DEFAULT 'montserrat'"
            )

    async def remember_username(self, user_id: int, username: str | None) -> None:
        await self.get(user_id)
        normalized = username.casefold() if username else None
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            if normalized:
                await connection.execute(
                    "UPDATE user_settings SET username = NULL WHERE username = ? AND user_id <> ?",
                    (normalized, user_id),
                )
            await connection.execute(
                "UPDATE user_settings SET username = ? WHERE user_id = ?",
                (normalized, user_id),
            )
            await connection.commit()

    async def find_user_id_by_username(self, username: str) -> int | None:
        normalized = username.removeprefix("@").casefold()
        async with aiosqlite.connect(self._database_path) as connection:
            cursor = await connection.execute(
                "SELECT user_id FROM user_settings WHERE username = ?",
                (normalized,),
            )
            row = await cursor.fetchone()
        return None if row is None else int(row[0])

    async def get(self, user_id: int) -> UserSettings:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute(
                "INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)",
                (user_id,),
            )
            cursor = await connection.execute(
                "SELECT * FROM user_settings WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            await connection.commit()
        if row is None:
            raise RuntimeError("failed to create user settings")
        return self._to_model(row)

    async def update(self, user_id: int, **values: Any) -> UserSettings:
        if not values or not set(values).issubset(_UPDATABLE_FIELDS):
            raise ValueError("unsupported settings update")
        await self.get(user_id)
        normalized = {key: self._db_value(value) for key, value in values.items()}
        assignments = ", ".join(f"{field} = ?" for field in normalized)
        parameters = [*normalized.values(), user_id]
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute(
                f"UPDATE user_settings SET {assignments}, updated_at = CURRENT_TIMESTAMP "  # noqa: S608
                "WHERE user_id = ?",
                parameters,
            )
            await connection.commit()
        return await self.get(user_id)

    async def set_pending_action(self, user_id: int, action: str | None) -> None:
        await self.get(user_id)
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute(
                "UPDATE user_settings SET pending_action = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE user_id = ?",
                (action, user_id),
            )
            await connection.commit()

    async def get_pending_action(self, user_id: int) -> str | None:
        await self.get(user_id)
        async with aiosqlite.connect(self._database_path) as connection:
            cursor = await connection.execute(
                "SELECT pending_action FROM user_settings WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else row[0]

    async def set_panel(self, user_id: int, chat_id: int, message_id: int) -> None:
        await self.get(user_id)
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute(
                "UPDATE user_settings SET panel_chat_id = ?, panel_message_id = ? "
                "WHERE user_id = ?",
                (chat_id, message_id, user_id),
            )
            await connection.commit()

    async def get_panel(self, user_id: int) -> tuple[int, int] | None:
        await self.get(user_id)
        async with aiosqlite.connect(self._database_path) as connection:
            cursor = await connection.execute(
                "SELECT panel_chat_id, panel_message_id FROM user_settings WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
        if row is None or row[0] is None or row[1] is None:
            return None
        return int(row[0]), int(row[1])

    async def clear_panel(self, user_id: int) -> None:
        await self.get(user_id)
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute(
                "UPDATE user_settings SET panel_chat_id = NULL, panel_message_id = NULL, "
                "panel_banner = NULL "
                "WHERE user_id = ?",
                (user_id,),
            )
            await connection.commit()

    async def set_panel_banner(self, user_id: int, banner_key: str) -> None:
        await self.get(user_id)
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute(
                "UPDATE user_settings SET panel_banner = ? WHERE user_id = ?",
                (banner_key, user_id),
            )
            await connection.commit()

    async def get_panel_banner(self, user_id: int) -> str | None:
        await self.get(user_id)
        async with aiosqlite.connect(self._database_path) as connection:
            cursor = await connection.execute(
                "SELECT panel_banner FROM user_settings WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else row[0]

    async def get_banner_cache(self, banner_key: str) -> tuple[str, str] | None:
        async with aiosqlite.connect(self._database_path) as connection:
            cursor = await connection.execute(
                "SELECT sha256, file_id FROM banner_cache WHERE banner_key = ?",
                (banner_key,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return str(row[0]), str(row[1])

    async def set_banner_cache(self, banner_key: str, sha256: str, file_id: str) -> None:
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute(
                "INSERT INTO banner_cache (banner_key, sha256, file_id) VALUES (?, ?, ?) "
                "ON CONFLICT(banner_key) DO UPDATE SET sha256 = excluded.sha256, "
                "file_id = excluded.file_id, updated_at = CURRENT_TIMESTAMP",
                (banner_key, sha256, file_id),
            )
            await connection.commit()

    async def delete_banner_cache(self, banner_key: str) -> None:
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute(
                "DELETE FROM banner_cache WHERE banner_key = ?",
                (banner_key,),
            )
            await connection.commit()

    async def set_preview_message(self, user_id: int, message_id: int | None) -> None:
        await self.get(user_id)
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute(
                "UPDATE user_settings SET preview_message_id = ? WHERE user_id = ?",
                (message_id, user_id),
            )
            await connection.commit()

    async def get_preview_message(self, user_id: int) -> int | None:
        await self.get(user_id)
        async with aiosqlite.connect(self._database_path) as connection:
            cursor = await connection.execute(
                "SELECT preview_message_id FROM user_settings WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
        return None if row is None or row[0] is None else int(row[0])

    async def set_sources(self, user_id: int, sources: list[SourceAsset]) -> None:
        await self.get(user_id)
        payload = json.dumps(
            [
                {
                    "file_id": source.file_id,
                    "file_unique_id": source.file_unique_id,
                    "kind": source.kind.value,
                    "emoji": source.emoji,
                    "custom_emoji_id": source.custom_emoji_id,
                    "needs_repainting": source.needs_repainting,
                    "premium_animation_file_id": source.premium_animation_file_id,
                }
                for source in sources
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        async with aiosqlite.connect(self._database_path) as connection:
            await connection.execute(
                "UPDATE user_settings SET last_sources_json = ? WHERE user_id = ?",
                (payload, user_id),
            )
            await connection.commit()

    async def get_sources(self, user_id: int) -> list[SourceAsset]:
        await self.get(user_id)
        async with aiosqlite.connect(self._database_path) as connection:
            cursor = await connection.execute(
                "SELECT last_sources_json FROM user_settings WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
        if row is None or not row[0]:
            return []
        try:
            payload = json.loads(row[0])
            return [
                SourceAsset(
                    file_id=item["file_id"],
                    file_unique_id=item["file_unique_id"],
                    kind=StickerKind(item["kind"]),
                    emoji=item.get("emoji"),
                    custom_emoji_id=item.get("custom_emoji_id"),
                    needs_repainting=bool(item.get("needs_repainting", False)),
                    premium_animation_file_id=item.get("premium_animation_file_id"),
                )
                for item in payload
            ]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return []

    @staticmethod
    def _db_value(value: Any) -> Any:
        return value.value if hasattr(value, "value") else value

    @staticmethod
    def _to_model(row: aiosqlite.Row) -> UserSettings:
        return UserSettings(
            user_id=int(row["user_id"]),
            balance_kopecks=int(row["balance_kopecks"]),
            background_kind=BackgroundKind(row["background_kind"]),
            background_color=str(row["background_color"]),
            background_file_id=row["background_file_id"],
            width=int(row["width"]),
            height=int(row["height"]),
            fps=int(row["fps"]),
            output_format=OutputFormat(row["output_format"]),
            emoji_size_percent=int(row["emoji_size_percent"]),
            emoji_color=row["emoji_color"],
            watermark_text=row["watermark_text"],
            watermark_position=WatermarkPosition(row["watermark_position"]),
            watermark_font=WatermarkFont(row["watermark_font"]),
        )
