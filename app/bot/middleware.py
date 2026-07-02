from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject


class UserRateLimitMiddleware(BaseMiddleware):
    def __init__(self, limit: int = 25, window_seconds: float = 10.0) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._events: dict[int, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)
        now = time.monotonic()
        async with self._lock:
            recent = self._events[user.id]
            while recent and recent[0] <= now - self._window_seconds:
                recent.popleft()
            if len(recent) >= self._limit:
                limited = True
            else:
                recent.append(now)
                limited = False
            if len(self._events) > 10_000:
                self._events = defaultdict(
                    deque,
                    {
                        user_id: timestamps
                        for user_id, timestamps in self._events.items()
                        if timestamps and timestamps[-1] > now - self._window_seconds
                    },
                )
        if not limited:
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer("Слишком много действий. Подождите несколько секунд.")
        return None
