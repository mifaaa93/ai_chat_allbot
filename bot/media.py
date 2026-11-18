"""Download Telegram media and turn it into LLM content."""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path

from telebot import types
from telebot.async_telebot import AsyncTeleBot

from llm.archive import ZipError, extract_zip
from llm.transcribe import Transcriber
from models_catalog import supports_vision

log = logging.getLogger(__name__)

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".yaml", ".yml", ".log", ".py"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
AUDIO_SUFFIXES = {".oga", ".ogg", ".mp3", ".m4a", ".wav", ".opus", ".aac"}
MAX_TEXT_FILE = 80_000
MAX_IMAGE = 8_000_000
MAX_ZIP_IMAGES = 8

_transcriber = Transcriber()


def status_label(message: types.Message) -> str:
    if message.voice or message.audio or message.video_note:
        return "Слушаю голос…"
    if message.photo:
        return "Смотрю картинку…"
    if message.document:
        suffix = Path(message.document.file_name or "").suffix.lower()
        if suffix in AUDIO_SUFFIXES:
            return "Слушаю голос…"
        if suffix in IMAGE_SUFFIXES:
            return "Смотрю картинку…"
        return "Читаю файл…"
    return "Думаю…"


def batch_status_label(messages: list[types.Message]) -> str:
    if len(messages) == 1:
        return status_label(messages[0])
    if is_album(messages):
        return f"Смотрю альбом ({len(messages)})…"
    if any(status_label(item).startswith("Слушаю") for item in messages):
        return f"Слушаю голос и разбираю пачку ({len(messages)})…"
    return f"Разбираю накопившиеся вопросы ({len(messages)})…"


def is_album(messages: list) -> bool:
    if not messages:
        return False
    group_id = getattr(messages[0], "media_group_id", None)
    if not group_id:
        return False
    return all(getattr(item, "media_group_id", None) == group_id for item in messages)


def units_status(units: list[list]) -> str:
    if len(units) == 1:
        return batch_status_label(units[0])
    flat = [item for unit in units for item in unit]
    if any(is_album(unit) for unit in units):
        return f"Разбираю альбом и ещё сообщения ({len(flat)})…"
    return batch_status_label(flat)


async def download_file(tg: AsyncTeleBot, file_id: str) -> tuple[bytes, str]:
    info = await tg.get_file(file_id)
    data = await tg.download_file(info.file_path)
    name = Path(info.file_path or "file").name
    return data, name


async def _voice_text(
    tg: AsyncTeleBot,
    file_id: str,
    fallback_suffix: str = ".oga",
    duration: int | None = None,
) -> str:
    data, name = await download_file(tg, file_id)
    suffix = Path(name).suffix or fallback_suffix
    log.info(
        "voice file=%s bytes=%s duration=%ss",
        name, len(data), duration if duration is not None else "?",
    )
    text = await asyncio.to_thread(_transcriber.transcribe, data, suffix, duration)
    return "Голос: " + text


async def user_payload(tg: AsyncTeleBot, message: types.Message, model: str) -> object:
    """Return content for the chat API."""
    caption = (message.caption or message.text or "").strip()
    if getattr(message, "video", None):
        raise RuntimeError("Видео пока не смотрю. Пришли фото, голос или файл.")
    if message.voice or message.audio or message.video_note:
        media = message.voice or message.audio or message.video_note
        duration = getattr(media, "duration", None)
        note = await _voice_text(tg, media.file_id, duration=duration)
        return note if not caption else f"{caption}\n\n{note}"
    if message.photo:
        photo = message.photo[-1]
        data, name = await download_file(tg, photo.file_id)
        return _vision_or_text(data, name, caption, model)
    if message.document:
        data, name = await download_file(tg, message.document.file_id)
        suffix = Path(message.document.file_name or name).suffix.lower()
        if suffix in AUDIO_SUFFIXES:
            note = await asyncio.to_thread(_transcriber.transcribe, data, suffix or ".oga")
            note = "Голос: " + note
            return note if not caption else f"{caption}\n\n{note}"
        if suffix in IMAGE_SUFFIXES:
            return _vision_or_text(data, name, caption, model)
        if suffix in TEXT_SUFFIXES:
            text = data.decode("utf-8", "replace")[:MAX_TEXT_FILE]
            body = f"Файл {name}:\n{text}"
            if caption:
                body = caption + "\n\n" + body
            return body
        if suffix == ".zip":
            return zip_to_content(data, message.document.file_name or name, caption, model)
        raise RuntimeError(f"Формат {suffix or name} пока не читаю. Пришли txt, md, csv, json, zip, картинку или голос.")
    if caption:
        return caption
    raise RuntimeError("Напиши текст, голос, картинку или файл.")


def _vision_or_text(data: bytes, name: str, caption: str, model: str):
    if not supports_vision(model):
        raise RuntimeError("Эта модель не смотрит картинки. Смени модель в /settings.")
    if len(data) > MAX_IMAGE:
        raise RuntimeError("Картинка слишком большая.")
    text = caption or "Опиши изображение и ответь по сути."
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": _data_url(data, name)}},
    ]


def _data_url(data: bytes, name: str) -> str:
    mime = "image/jpeg"
    suffix = Path(name).suffix.lower()
    if suffix == ".png":
        mime = "image/png"
    elif suffix == ".webp":
        mime = "image/webp"
    elif suffix == ".gif":
        mime = "image/gif"
    return "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")


def bytes_to_content(data: bytes, name: str, model: str, caption: str = ""):
    suffix = Path(name).suffix.lower()
    if suffix in TEXT_SUFFIXES:
        text = data.decode("utf-8", "replace")[:MAX_TEXT_FILE]
        body = f"Содержимое файла {name}:\n{text}"
        return caption + "\n\n" + body if caption else body
    if suffix == ".zip":
        return zip_to_content(data, name, caption, model)
    if suffix in IMAGE_SUFFIXES:
        return _vision_or_text(data, name, caption or f"Файл {name}.", model)
    if suffix == ".pdf":
        note = f"Файл {name}: PDF. Правь исходный текст, если он есть в контексте, и пересобери write_file."
        return caption + "\n\n" + note if caption else note
    note = f"Файл {name}: вложение {len(data)} байт, этот формат целиком в чат не кладу."
    return caption + "\n\n" + note if caption else note


def zip_to_content(data: bytes, name: str, caption: str, model: str):
    try:
        members = extract_zip(data)
    except ZipError as exc:
        raise RuntimeError(str(exc)) from exc
    notes: list[str] = []
    texts: list[str] = []
    images: list[tuple[str, bytes]] = []
    for filename, payload in members:
        suffix = Path(filename).suffix.lower()
        if suffix in TEXT_SUFFIXES:
            texts.append(f"Файл {filename}:\n{payload.decode('utf-8', 'replace')[:MAX_TEXT_FILE]}")
        elif suffix in IMAGE_SUFFIXES:
            if len(images) >= MAX_ZIP_IMAGES:
                notes.append(f"Картинку {filename} пропустил: слишком много изображений в архиве.")
            elif len(payload) > MAX_IMAGE:
                notes.append(f"Картинка {filename} слишком большая.")
            else:
                images.append((filename, payload))
        else:
            notes.append(f"Файл {filename} пропустил.")
    header = f"Архив {name}."
    if caption:
        header = caption + "\n\n" + header
    body = "\n\n".join([header, *texts, *notes]).strip()
    if images and not supports_vision(model):
        body += "\n\nВ архиве есть картинки, но эта модель их не смотрит."
        return body
    if not images:
        return body or f"Архив {name} пустой."
    parts = [{"type": "text", "text": body or "Архив с картинками."}]
    for filename, payload in images:
        parts.append({"type": "image_url", "image_url": {"url": _data_url(payload, filename)}})
    return parts


async def unit_payload(tg: AsyncTeleBot, messages: list[types.Message], model: str):
    if is_album(messages) or len(messages) > 1:
        return await album_payload(tg, messages, model)
    return await user_payload(tg, messages[0], model)


async def album_payload(tg: AsyncTeleBot, messages: list[types.Message], model: str):
    caption = ""
    notes: list[str] = []
    texts: list[str] = []
    images: list[tuple[str, bytes]] = []
    extra_parts: list[dict] = []
    for index, message in enumerate(messages, start=1):
        cap = (message.caption or "").strip()
        if cap and not caption:
            caption = cap
        video = getattr(message, "video", None)
        if message.photo:
            photo = message.photo[-1]
            data, name = await download_file(tg, photo.file_id)
            images.append((name or f"photo-{index}.jpg", data))
            continue
        if message.document:
            data, name = await download_file(tg, message.document.file_id)
            filename = message.document.file_name or name
            suffix = Path(filename).suffix.lower()
            if suffix in IMAGE_SUFFIXES:
                images.append((filename, data))
            elif suffix in TEXT_SUFFIXES:
                texts.append(f"Файл {filename}:\n{data.decode('utf-8', 'replace')[:MAX_TEXT_FILE]}")
            elif suffix == ".zip":
                nested = zip_to_content(data, filename, "", model)
                if isinstance(nested, str):
                    texts.append(nested)
                else:
                    for part in nested:
                        if part.get("type") == "image_url":
                            extra_parts.append(part)
                        elif part.get("text"):
                            texts.append(part["text"])
            else:
                notes.append(f"Вложение {filename} пропустил.")
            continue
        if video or message.video_note:
            notes.append("Видео в альбоме пропускаю.")
            continue
        text = (message.text or "").strip()
        if text and not caption:
            caption = text
    if (images or extra_parts) and not supports_vision(model):
        raise RuntimeError("Эта модель не смотрит картинки. Смени модель в /settings.")
    header = f"Альбом из {len(messages)} вложений."
    if caption:
        header = caption + "\n\n" + header
    body = "\n\n".join(bit for bit in [header, *texts, *notes] if bit)
    if not images and not extra_parts:
        return body or "Пустой альбом."
    parts = [{"type": "text", "text": body}]
    for name, data in images:
        if len(data) > MAX_IMAGE:
            parts.append({"type": "text", "text": f"{name}: картинка слишком большая."})
            continue
        parts.append({"type": "image_url", "image_url": {"url": _data_url(data, name)}})
    parts.extend(extra_parts)
    return parts
