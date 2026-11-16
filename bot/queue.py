"""Per-chat follow-up queue: collect messages while a turn is running."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from config import ALBUM_WAIT_SECONDS, MAX_PENDING_PER_CHAT


def content_preview(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            part.get("text")
            for part in content
            if isinstance(part, dict) and part.get("text")
        ]
        return "\n".join(texts) or "[изображение]"
    return str(content)


def combine_user_contents(contents: list) -> object:
    if len(contents) == 1:
        return contents[0]
    header = (
        f"Пока готовился предыдущий ответ, пользователь отправил ещё {len(contents)} сообщений. "
        "Ответь на ВСЕ одним сообщением, отдельными разделами в исходном порядке. Не пропускай вопросы."
    )
    if all(isinstance(item, str) for item in contents):
        body = "\n\n".join(f"{index}. {item}" for index, item in enumerate(contents, start=1))
        return header + "\n\n" + body
    parts: list[dict] = [{"type": "text", "text": header}]
    for index, item in enumerate(contents, start=1):
        if isinstance(item, str):
            parts.append({"type": "text", "text": f"{index}. {item}"})
            continue
        parts.append({"type": "text", "text": f"{index}."})
        if isinstance(item, list):
            parts.extend(item)
        else:
            parts.append({"type": "text", "text": str(item)})
    return parts


class AlbumGate:
    """Wait until a Telegram media group stops arriving, then return all items."""

    def __init__(self, delay: float = ALBUM_WAIT_SECONDS):
        self.delay = delay
        self._lock = asyncio.Lock()
        self._buckets: dict[tuple[int, str], list] = {}
        self._stamp: dict[tuple[int, str], int] = {}

    async def take(self, message) -> list | None:
        group_id = getattr(message, "media_group_id", None)
        if not group_id:
            return [message]
        key = (message.chat.id, str(group_id))
        async with self._lock:
            first = key not in self._buckets
            self._buckets.setdefault(key, []).append(message)
            self._stamp[key] = self._stamp.get(key, 0) + 1
            stamp = self._stamp[key]
            if not first:
                return None
        while True:
            await asyncio.sleep(self.delay)
            async with self._lock:
                if key not in self._buckets:
                    return []
                if self._stamp[key] != stamp:
                    stamp = self._stamp[key]
                    continue
                return self._buckets.pop(key)

    async def clear_chat(self, chat_id: int) -> None:
        async with self._lock:
            keys = [key for key in self._buckets if key[0] == chat_id]
            for key in keys:
                self._buckets.pop(key, None)
                self._stamp[key] = self._stamp.get(key, 0) + 1


class ChatWork:
    def __init__(self, limit: int = MAX_PENDING_PER_CHAT):
        self.limit = limit
        self._guard = asyncio.Lock()
        self._busy: set[int] = set()
        self._pending: dict[int, list] = defaultdict(list)

    async def submit(self, chat_id: int, message) -> str:
        return await self.submit_batch(chat_id, [message])

    async def submit_batch(self, chat_id: int, messages: list) -> str:
        if not messages:
            return "empty"
        async with self._guard:
            if chat_id in self._busy:
                bucket = self._pending[chat_id]
                if len(bucket) >= self.limit:
                    return "full"
                bucket.append(list(messages))
                return "queued"
            self._busy.add(chat_id)
            return "run"

    async def pending_count(self, chat_id: int) -> int:
        async with self._guard:
            return len(self._pending.get(chat_id, []))

    async def pop_pending(self, chat_id: int) -> list:
        async with self._guard:
            return self._pending.pop(chat_id, [])

    async def finish_or_continue(self, chat_id: int) -> list:
        """Return pending units (each a list of messages), or mark idle."""
        async with self._guard:
            batch = self._pending.pop(chat_id, [])
            if not batch:
                self._busy.discard(chat_id)
            return batch

    async def clear_pending(self, chat_id: int) -> None:
        async with self._guard:
            self._pending.pop(chat_id, None)

    async def abort(self, chat_id: int) -> None:
        async with self._guard:
            self._busy.discard(chat_id)
            self._pending.pop(chat_id, None)
