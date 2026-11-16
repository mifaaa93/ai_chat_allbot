"""Per-chat follow-up queue: collect messages while a turn is running."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from config import MAX_PENDING_PER_CHAT


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


class ChatWork:
    def __init__(self, limit: int = MAX_PENDING_PER_CHAT):
        self.limit = limit
        self._guard = asyncio.Lock()
        self._busy: set[int] = set()
        self._pending: dict[int, list] = defaultdict(list)

    async def submit(self, chat_id: int, message) -> str:
        async with self._guard:
            if chat_id in self._busy:
                bucket = self._pending[chat_id]
                if len(bucket) >= self.limit:
                    return "full"
                bucket.append(message)
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
        """Return next batch, or mark idle if nothing is waiting."""
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
