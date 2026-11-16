"""Fit answers into Telegram Rich Message or plain text."""

from __future__ import annotations

from telebot import types

RICH_LIMIT = 32000
PLAIN_LIMIT = 4000


def fit(text: str, limit: int) -> str:
    payload = (text or "").strip() or "Пустой ответ."
    encoded = payload.encode("utf-8")
    if len(encoded) <= limit:
        return payload
    cut = payload.encode("utf-8")[: limit - 40]
    trimmed = cut.decode("utf-8", "ignore")
    if "\n" in trimmed:
        trimmed = trimmed.rsplit("\n", 1)[0]
    return trimmed.rstrip() + "\n…"


def rich_message(text: str) -> types.InputRichMessage:
    return types.InputRichMessage(markdown=fit(text, RICH_LIMIT))
