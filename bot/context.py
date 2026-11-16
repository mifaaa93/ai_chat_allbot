"""Reply/quote context and recent-file hydration for the model."""

from __future__ import annotations

import logging
import re
from contextlib import closing
from pathlib import Path

from telebot.async_telebot import AsyncTeleBot

from bot.media import bytes_to_content, download_file
from bot.queue import content_preview
from db import add_file, list_files, open_db

log = logging.getLogger(__name__)

EDIT_HINT = re.compile(
    r"поправ|исправ|измени|замен|добав|удали|перепиши|пересобери|файл|архив|\bzip\b|"
    r"\.(zip|pdf|txt|md|py|json|csv|html)\b|\bedit\b|\bfix\b|обнови",
    re.I,
)
MAX_FETCH = 4


def quote_text(message) -> str:
    quote = getattr(message, "quote", None)
    if quote is None:
        return ""
    return (getattr(quote, "text", None) or "").strip()


def format_reply(message) -> str:
    reply = getattr(message, "reply_to_message", None)
    quoted = quote_text(message)
    if reply is None and not quoted:
        return ""
    lines = ["Пользователь отвечает на сообщение."]
    if quoted:
        lines.append("Цитата:\n" + quoted)
    if reply is not None:
        body = ((reply.text or reply.caption) or "").strip()
        if body and body != quoted:
            label = "Текст сообщения" if quoted else "Сообщение"
            lines.append(f"{label}:\n{body[:4000]}")
        media = _describe_media(reply)
        if media:
            lines.append(media)
        lines.append(f"message_id={reply.message_id}")
    return "\n".join(lines)


def _describe_media(message) -> str:
    document = getattr(message, "document", None)
    if document is not None:
        name = getattr(document, "file_name", None) or "document"
        return f"Вложение: файл {name}"
    if getattr(message, "photo", None):
        return "Вложение: фото"
    if getattr(message, "voice", None) or getattr(message, "audio", None):
        return "Вложение: голос"
    if getattr(message, "video", None) or getattr(message, "video_note", None):
        return "Вложение: видео"
    return ""


def file_refs_from_message(message, origin: str = "user") -> list[dict]:
    refs: list[dict] = []
    message_id = getattr(message, "message_id", None)
    document = getattr(message, "document", None)
    if document is not None and getattr(document, "file_id", None):
        refs.append({
            "tg_file_id": document.file_id,
            "tg_message_id": message_id,
            "filename": document.file_name or "file",
            "kind": "document",
            "origin": origin,
        })
    photos = getattr(message, "photo", None) or []
    if photos and getattr(photos[-1], "file_id", None):
        refs.append({
            "tg_file_id": photos[-1].file_id,
            "tg_message_id": message_id,
            "filename": f"photo-{message_id or 'x'}.jpg",
            "kind": "photo",
            "origin": origin,
        })
    return refs


def first_reply_message(units: list[list]) -> object | None:
    for unit in units:
        for message in unit:
            if getattr(message, "reply_to_message", None) or quote_text(message):
                return message
    return None


def looks_like_file_edit(text: str) -> bool:
    return bool(EDIT_HINT.search(text or ""))


def select_files(user_text: str, files: list[dict], reply_message, skip_ids: set[str]) -> list[dict]:
    chosen: list[dict] = []
    seen: set[str] = set()

    def add(row: dict) -> None:
        file_id = row.get("tg_file_id")
        if not file_id or file_id in seen or file_id in skip_ids:
            return
        seen.add(file_id)
        chosen.append(row)

    if reply_message is not None:
        reply = getattr(reply_message, "reply_to_message", None)
        reply_id = getattr(reply, "message_id", None)
        if reply_id is not None:
            for row in files:
                if row.get("tg_message_id") == reply_id or row.get("anchor_message_id") == reply_id:
                    add(row)
        if reply is not None:
            for ref in file_refs_from_message(reply, origin="reply"):
                add(ref)

    lowered = (user_text or "").lower()
    for row in files:
        name = (row.get("filename") or "").lower()
        if name and name in lowered:
            add(row)

    if not chosen and looks_like_file_edit(user_text):
        for row in reversed(files):
            if row.get("origin") == "bot" and row.get("kind") == "document":
                add(row)
                if len(chosen) >= 2:
                    break
        if not chosen:
            for row in reversed(files):
                add(row)
                break
    return chosen[:MAX_FETCH]


def inventory_text(files: list[dict]) -> str:
    if not files:
        return ""
    lines = ["Недавние файлы этого диалога:"]
    for index, row in enumerate(files, start=1):
        who = "бот" if row.get("origin") == "bot" else "пользователь"
        lines.append(f"{index}. {row.get('filename')} ({who})")
    return "\n".join(lines)


def merge_content(prefix: str, extra_parts: list, content):
    texts: list[str] = []
    images: list[dict] = []
    if prefix and prefix.strip():
        texts.append(prefix.strip())
    for part in extra_parts:
        _collect_parts(part, texts, images)
    header = "\n\n".join(texts)
    if not header and not images:
        return content
    if isinstance(content, list):
        body = list(content)
        if header:
            body.insert(0, {"type": "text", "text": header})
        return images + body
    if images:
        lead = header + "\n\n" + content if header else content
        return [{"type": "text", "text": lead}, *images]
    return header + "\n\n" + content if header else content


def _collect_parts(part, texts: list[str], images: list[dict]) -> None:
    if not part:
        return
    if isinstance(part, str):
        texts.append(part.strip())
        return
    if isinstance(part, list):
        for item in part:
            _collect_parts(item, texts, images)
        return
    if isinstance(part, dict):
        if part.get("type") == "image_url":
            images.append(part)
        elif part.get("text"):
            texts.append(part["text"])



def current_file_ids(units: list[list]) -> set[str]:
    ids: set[str] = set()
    for unit in units:
        for message in unit:
            for ref in file_refs_from_message(message):
                ids.add(ref["tg_file_id"])
    return ids


def save_user_files(user_id: int, thread_id: str, units: list[list]) -> None:
    with closing(open_db()) as conn:
        for unit in units:
            for message in unit:
                for ref in file_refs_from_message(message, origin="user"):
                    add_file(conn, user_id, thread_id, **ref)


def save_bot_files(
    user_id: int,
    thread_id: str,
    records: list[dict],
    anchor_message_id: int | None,
) -> None:
    if not records:
        return
    with closing(open_db()) as conn:
        for record in records:
            add_file(
                conn, user_id, thread_id,
                tg_file_id=record["tg_file_id"],
                filename=record.get("filename") or "file",
                kind=record.get("kind") or "document",
                origin=record.get("origin") or "bot",
                tg_message_id=record.get("tg_message_id"),
                anchor_message_id=anchor_message_id,
                source_text=record.get("source_text"),
            )


async def attach_context(
    tg: AsyncTeleBot,
    content,
    units: list[list],
    user_id: int,
    thread_id: str,
    model: str,
):
    reply_message = first_reply_message(units)
    reply_block = format_reply(reply_message) if reply_message is not None else ""
    user_text = content_preview(content)
    with closing(open_db()) as conn:
        stored = list_files(conn, user_id, thread_id)
    skip = current_file_ids(units)
    chosen = select_files(user_text, stored, reply_message, skip)
    extra_parts: list = []
    for row in chosen:
        extra_parts.append(await _hydrate_row(tg, row, model))
    prefix_bits = []
    if reply_block:
        prefix_bits.append(reply_block)
    if chosen or (stored and (reply_block or looks_like_file_edit(user_text))):
        listing = inventory_text(stored)
        if listing:
            prefix_bits.append(listing)
    prefix = "\n\n".join(prefix_bits)
    return merge_content(prefix, extra_parts, content)


async def _hydrate_row(tg: AsyncTeleBot, row: dict, model: str):
    name = row.get("filename") or "file"
    source = (row.get("source_text") or "").strip()
    if source:
        return f"Исходный текст файла {name} (последняя известная версия):\n{source}"
    file_id = row.get("tg_file_id")
    if not file_id:
        return f"Файл {name}: нет telegram file_id."
    try:
        data, downloaded_name = await download_file(tg, file_id)
    except Exception:
        log.warning("failed to download stored file %s", name, exc_info=True)
        return f"Файл {name}: не удалось скачать из Telegram."
    filename = name if Path(name).suffix else downloaded_name
    try:
        return bytes_to_content(data, filename, model, caption=f"Файл {filename} из Telegram.")
    except Exception as exc:
        return f"Файл {filename}: не разобрал содержимое ({exc})."
