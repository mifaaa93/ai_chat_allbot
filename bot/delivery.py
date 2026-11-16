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
    image_prompts: list[str] | None = None,
    files=None,
) -> list[dict]:
    saved: list[dict] = []
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
        name = f"image-{index + 1}.png"
        photo.name = name
        sent = await tg.send_photo(chat_id, photo)
        file_id = _photo_file_id(sent)
        if file_id:
            prompt = ""
            if image_prompts and index < len(image_prompts):
                prompt = image_prompts[index]
            saved.append({
                "tg_file_id": file_id,
                "tg_message_id": sent.message_id,
                "filename": name,
                "kind": "photo",
                "origin": "bot",
                "source_text": prompt or None,
            })
    for item in files or []:
        name, payload, source = _unpack_file(item)
        document = BytesIO(payload)
        document.name = name
        sent = await tg.send_document(chat_id, document, visible_file_name=name)
        file_id = getattr(getattr(sent, "document", None), "file_id", None)
        if file_id:
            saved.append({
                "tg_file_id": file_id,
                "tg_message_id": sent.message_id,
                "filename": name,
                "kind": "document",
                "origin": "bot",
                "source_text": source,
            })
    return saved


def _photo_file_id(sent) -> str | None:
    photos = getattr(sent, "photo", None) or []
    if photos:
        return photos[-1].file_id
    return None


def _unpack_file(item) -> tuple[str, bytes, str | None]:
    filename = getattr(item, "filename", None)
    if filename:
        return filename, item.data, getattr(item, "source_text", None)
    name, payload = item[0], item[1]
    source = item[2] if len(item) > 2 else None
    return name, payload, source
