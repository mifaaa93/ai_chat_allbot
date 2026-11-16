"""Status message and rich edit with plain fallback."""

from __future__ import annotations

import logging
from io import BytesIO

from telebot.apihelper import ApiTelegramException
from telebot.async_telebot import AsyncTeleBot

from bot.rich import PLAIN_LIMIT, fit, rich_message

log = logging.getLogger(__name__)


async def send_status(tg: AsyncTeleBot, chat_id: int, text: str, reply_to: int | None = None):
    try:
        return await tg.send_message(chat_id, text, reply_to_message_id=reply_to)
    except ApiTelegramException:
        return await tg.send_message(chat_id, text)


async def edit_status(tg: AsyncTeleBot, chat_id: int, message_id: int, text: str) -> None:
    try:
        await tg.edit_message_text(text, chat_id, message_id)
    except ApiTelegramException:
        log.debug("status edit skipped", exc_info=True)


async def deliver_answer(
    tg: AsyncTeleBot,
    chat_id: int,
    message_id: int,
    text: str,
    images: list[bytes] | None = None,
    files: list[tuple[str, bytes]] | None = None,
) -> None:
    try:
        await tg.edit_message_text(
            None, chat_id, message_id, rich_message=rich_message(text),
        )
    except Exception:
        log.warning("Rich edit failed, sending plain", exc_info=True)
        try:
            await tg.edit_message_text(fit(text, PLAIN_LIMIT), chat_id, message_id)
        except Exception:
            await tg.send_message(chat_id, fit(text, PLAIN_LIMIT))
    for index, image in enumerate(images or []):
        photo = BytesIO(image)
        photo.name = f"image-{index + 1}.png"
        await tg.send_photo(chat_id, photo)
    for name, payload in files or []:
        document = BytesIO(payload)
        document.name = name
        await tg.send_document(chat_id, document, visible_file_name=name)
