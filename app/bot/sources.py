from __future__ import annotations

import re

from aiogram import Bot
from aiogram.types import Message, Sticker

from app.models import SourceAsset, StickerKind

_PACK_LINK = re.compile(
    r"(?:https?://)?t\.me/(?:addstickers|addemoji)/([A-Za-z0-9_]{1,64})(?:\?.*)?$",
    re.IGNORECASE,
)


async def extract_sources(message: Message, bot: Bot) -> list[SourceAsset]:
    if message.sticker:
        return [_from_sticker(message.sticker)]

    custom_emoji_ids: list[str] = []
    for entity in [*(message.entities or []), *(message.caption_entities or [])]:
        if entity.type == "custom_emoji" and entity.custom_emoji_id:
            if entity.custom_emoji_id not in custom_emoji_ids:
                custom_emoji_ids.append(entity.custom_emoji_id)
    if custom_emoji_ids:
        stickers = await bot.get_custom_emoji_stickers(custom_emoji_ids[:8])
        return [_from_sticker(sticker) for sticker in stickers]

    text = (message.text or message.caption or "").strip()
    match = _PACK_LINK.fullmatch(text)
    if match:
        sticker_set = await bot.get_sticker_set(match.group(1))
        return [_from_sticker(sticker) for sticker in sticker_set.stickers[:8]]
    return []


def _from_sticker(sticker: Sticker) -> SourceAsset:
    kind = (
        StickerKind.TGS
        if sticker.is_animated
        else StickerKind.VIDEO
        if sticker.is_video
        else StickerKind.STATIC
    )
    premium_animation = sticker.premium_animation.file_id if sticker.premium_animation else None
    return SourceAsset(
        file_id=sticker.file_id,
        file_unique_id=sticker.file_unique_id,
        kind=kind,
        emoji=sticker.emoji,
        custom_emoji_id=sticker.custom_emoji_id,
        needs_repainting=bool(sticker.needs_repainting),
        premium_animation_file_id=premium_animation,
    )
