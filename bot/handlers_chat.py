"""Private chat: text, voice, photos, files."""

from __future__ import annotations

import asyncio
import logging
from contextlib import closing, suppress

import requests
from telebot import types
from telebot.async_telebot import AsyncTeleBot

from bot.context import attach_context, save_bot_files, save_user_files
from bot.delivery import (
    deliver_answer,
    edit_status,
    send_generated_file,
    send_generated_image,
    send_status,
)
from bot.media import unit_payload, units_status
from bot.progress import (
    TurnStatus,
    chat_action_for,
    retry_label,
    tool_done_label,
    tool_label,
)
from bot.queue import AlbumGate, ChatWork, combine_user_contents, content_preview
from config import HEARTBEAT_SECONDS, allowed_user_ids
from db import add_message, get_or_create_user, load_history, open_db
from llm.client import ChatClient

log = logging.getLogger(__name__)
_client = ChatClient()
_work = ChatWork()
_albums = AlbumGate()
_queue_notice: dict[int, int] = {}

START_TEXT = (
    "Привет. Это ИИ-бот.\n\n"
    "Пиши как в ChatGPT: текст, голос, картинки, альбомы и файлы.\n"
    "/settings — модель, стиль, картинки\n"
    "/new — новый диалог"
)


def allowed(user_id: int) -> bool:
    ids = allowed_user_ids()
    return not ids or user_id in ids


async def clear_chat_queue(chat_id: int) -> None:
    await _albums.clear_chat(chat_id)
    await _work.clear_pending(chat_id)
    _queue_notice.pop(chat_id, None)


def _load_user(user_id: int) -> dict:
    with closing(open_db()) as conn:
        return dict(get_or_create_user(conn, user_id))


def _complete_sync(user_id: int, content, stored: str | None = None, on_progress=None):
    with closing(open_db()) as conn:
        settings = dict(get_or_create_user(conn, user_id))
        thread_id = settings["thread_id"]
        history = load_history(conn, settings["user_id"], thread_id)
    result = _client.complete(
        history,
        content,
        model=settings["model"],
        reasoning=settings["reasoning"],
        style=settings["style"],
        image_quality=settings["image_quality"],
        on_progress=on_progress,
    )
    preview = (stored if stored is not None else content_preview(content))[:12000]
    with closing(open_db()) as conn:
        add_message(conn, user_id, thread_id, "user", preview)
        add_message(conn, user_id, thread_id, "assistant", result.text[:12000])
    return result


async def _note_queued(tg: AsyncTeleBot, chat_id: int) -> None:
    count = await _work.pending_count(chat_id)
    text = f"В очереди {count}. Отвечу пачкой после текущего ответа."
    notice_id = _queue_notice.get(chat_id)
    if notice_id:
        try:
            await tg.edit_message_text(text, chat_id, notice_id)
            return
        except Exception:
            pass
    sent = await tg.send_message(chat_id, text)
    _queue_notice[chat_id] = sent.message_id


async def _clear_notice(tg: AsyncTeleBot, chat_id: int) -> None:
    notice_id = _queue_notice.pop(chat_id, None)
    if notice_id is None:
        return
    try:
        await tg.delete_message(chat_id, notice_id)
    except Exception:
        try:
            await tg.edit_message_text("Разбираю накопившиеся вопросы…", chat_id, notice_id)
        except Exception:
            pass


async def _heartbeat(tg: AsyncTeleBot, chat_id: int, message_id: int, clock: TurnStatus) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        try:
            await tg.send_chat_action(chat_id, clock.action)
        except Exception:
            log.debug("heartbeat action skipped", exc_info=True)
        await edit_status(tg, chat_id, message_id, clock.text())


async def _run_turn(tg: AsyncTeleBot, units: list[list[types.Message]]) -> None:
    first = units[0][0]
    user = first.from_user
    chat_id = first.chat.id
    settings = await asyncio.to_thread(_load_user, user.id)
    try:
        await tg.send_chat_action(chat_id, "typing")
    except Exception:
        pass
    status = await send_status(tg, chat_id, units_status(units), first.message_id)
    clock = TurnStatus(units_status(units))
    records: list[dict] = []
    sent_files: set[int] = set()
    sent_images: set[int] = set()
    image_index = 0
    loop = asyncio.get_running_loop()

    async def apply_progress(event: str, payload: dict) -> None:
        nonlocal image_index
        if event == "thinking":
            if clock.used_tools:
                clock.set_label("Собираю ответ…", "typing")
            else:
                clock.action = "typing"
            await edit_status(tg, chat_id, status.message_id, clock.text())
            return
        if event == "retry":
            clock.set_label(
                retry_label(
                    payload.get("attempt") or 1,
                    payload.get("budget") or 1,
                    payload.get("status"),
                    timeout=bool(payload.get("timeout")),
                ),
                "typing",
            )
            await edit_status(tg, chat_id, status.message_id, clock.text())
            return
        if event == "tool":
            name = str(payload.get("name") or "")
            args = payload.get("args") or {}
            clock.used_tools = True
            clock.set_label(tool_label(name, args), chat_action_for(name))
            try:
                await tg.send_chat_action(chat_id, clock.action)
            except Exception:
                pass
            await edit_status(tg, chat_id, status.message_id, clock.text())
            return
        if event != "tool_done":
            return
        name = str(payload.get("name") or "")
        args = payload.get("args") or {}
        outfile = payload.get("file")
        image = payload.get("image")
        sent = False
        if outfile is not None:
            try:
                record = await send_generated_file(tg, chat_id, outfile)
            except Exception:
                log.exception("early file send failed")
                record = None
            if record:
                records.append(record)
                sent_files.add(id(outfile))
                sent = True
        elif image is not None:
            try:
                record = await send_generated_image(
                    tg, chat_id, image, index=image_index,
                    prompt=str(payload.get("image_prompt") or ""),
                )
            except Exception:
                log.exception("early image send failed")
                record = None
            if record:
                records.append(record)
                sent_images.add(id(image))
                sent = True
            image_index += 1
        clock.used_tools = True
        clock.set_label(tool_done_label(name, args, sent=sent), "typing")
        await edit_status(tg, chat_id, status.message_id, clock.text())

    def on_progress(event: str, **payload):
        future = asyncio.run_coroutine_threadsafe(apply_progress(event, payload), loop)
        if event == "tool_done" and (
            payload.get("file") is not None or payload.get("image") is not None
        ):
            try:
                future.result(timeout=90)
            except Exception:
                log.exception("progress wait failed")

    beat = asyncio.create_task(_heartbeat(tg, chat_id, status.message_id, clock))
    try:
        try:
            payloads = [await unit_payload(tg, unit, settings["model"]) for unit in units]
            raw = payloads[0] if len(payloads) == 1 else combine_user_contents(payloads)
            await asyncio.to_thread(save_user_files, user.id, settings["thread_id"], units)
            content = await attach_context(
                tg, raw, units, user.id, settings["thread_id"], settings["model"],
            )
            stored = content_preview(raw)[:12000]
        except Exception as exc:
            log.warning("payload failed error=%s", exc)
            await edit_status(tg, chat_id, status.message_id, str(exc)[:400])
            return
        try:
            result = await asyncio.to_thread(
                _complete_sync, user.id, content, stored, on_progress,
            )
        except requests.Timeout:
            log.exception("chat timeout")
            await edit_status(
                tg, chat_id, status.message_id,
                "Провайдер не ответил вовремя. Попробуй ещё раз.",
            )
            return
        except Exception:
            log.exception("chat failed")
            await edit_status(
                tg, chat_id, status.message_id,
                "Не получилось ответить. Попробуй ещё раз.",
            )
            return
    finally:
        beat.cancel()
        with suppress(asyncio.CancelledError):
            await beat

    leftover_files = [item for item in result.files if id(item) not in sent_files]
    leftover_images = []
    leftover_prompts = []
    for index, image in enumerate(result.images):
        if id(image) in sent_images:
            continue
        leftover_images.append(image)
        prompt = ""
        if index < len(result.image_prompts):
            prompt = result.image_prompts[index]
        leftover_prompts.append(prompt)
    later = await deliver_answer(
        tg, chat_id, status.message_id, result.text,
        images=leftover_images, image_prompts=leftover_prompts, files=leftover_files,
    )
    records.extend(later)
    await asyncio.to_thread(
        save_bot_files, user.id, settings["thread_id"], records, status.message_id,
    )


def register(tg: AsyncTeleBot) -> None:
    @tg.message_handler(commands=["start", "help"])
    async def start_cmd(message: types.Message) -> None:
        if not allowed(message.from_user.id):
            return
        await asyncio.to_thread(_load_user, message.from_user.id)
        await tg.send_message(message.chat.id, START_TEXT)

    @tg.message_handler(
        chat_types=["private"],
        content_types=["text", "voice", "audio", "photo", "document", "video", "video_note"],
    )
    async def chat_cmd(message: types.Message) -> None:
        if message.text and message.text.startswith("/"):
            return
        user = message.from_user
        if user is None or not allowed(user.id):
            return
        log.info(
            "incoming chat_id=%s user_id=%s content=%s group=%s",
            message.chat.id, user.id, message.content_type,
            getattr(message, "media_group_id", None),
        )
        batch = await _albums.take(message)
        if not batch:
            return
        state = await _work.submit_batch(message.chat.id, batch)
        if state == "queued":
            await _note_queued(tg, message.chat.id)
            return
        if state == "full":
            await tg.send_message(
                message.chat.id,
                "Очередь полная. Дождись ответа и напиши снова.",
            )
            return
        try:
            units = [batch]
            while units:
                await _clear_notice(tg, message.chat.id)
                await _run_turn(tg, units)
                units = await _work.finish_or_continue(message.chat.id)
        except Exception:
            log.exception("chat loop failed")
            await _work.abort(message.chat.id)
            try:
                await tg.send_message(message.chat.id, "Не получилось ответить. Попробуй ещё раз.")
            except Exception:
                pass
