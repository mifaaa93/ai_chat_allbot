"""Download Telegram media and turn it into LLM content."""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path

from telebot import types
from telebot.async_telebot import AsyncTeleBot

from llm.transcribe import Transcriber
from models_catalog import supports_vision

log = logging.getLogger(__name__)

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".yaml", ".yml", ".log", ".py"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
AUDIO_SUFFIXES = {".oga", ".ogg", ".mp3", ".m4a", ".wav", ".opus", ".aac"}
MAX_TEXT_FILE = 80_000
MAX_IMAGE = 8_000_000

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
    if any(status_label(item).startswith("Слушаю") for item in messages):
        return f"Слушаю голос и разбираю пачку ({len(messages)})…"
    return f"Разбираю накопившиеся вопросы ({len(messages)})…"


async def download_file(tg: AsyncTeleBot, file_id: str) -> tuple[bytes, str]:
    info = await tg.get_file(file_id)
    data = await tg.download_file(info.file_path)
    name = Path(info.file_path or "file").name
    return data, name


async def _voice_text(tg: AsyncTeleBot, file_id: str, fallback_suffix: str = ".oga") -> str:
    data, name = await download_file(tg, file_id)
    suffix = Path(name).suffix or fallback_suffix
    text = await asyncio.to_thread(_transcriber.transcribe, data, suffix)
    return "Голос: " + text


async def user_payload(tg: AsyncTeleBot, message: types.Message, model: str) -> object:
    """Return content for the chat API."""
    caption = (message.caption or message.text or "").strip()
    if message.voice or message.audio or message.video_note:
        media = message.voice or message.audio or message.video_note
        note = await _voice_text(tg, media.file_id)
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
        raise RuntimeError(f"Формат {suffix or name} пока не читаю. Пришли txt, md, csv, json, картинку или голос.")
    if caption:
        return caption
    raise RuntimeError("Напиши текст, голос, картинку или файл.")


def _vision_or_text(data: bytes, name: str, caption: str, model: str):
    if not supports_vision(model):
        raise RuntimeError("Эта модель не смотрит картинки. Смени модель в /settings.")
    if len(data) > MAX_IMAGE:
        raise RuntimeError("Картинка слишком большая.")
    mime = "image/jpeg"
    suffix = Path(name).suffix.lower()
    if suffix == ".png":
        mime = "image/png"
    elif suffix == ".webp":
        mime = "image/webp"
    elif suffix == ".gif":
        mime = "image/gif"
    url = "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")
    text = caption or "Опиши изображение и ответь по сути."
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": url}},
    ]
