"""Private chat: text, voice, photos, files."""

from __future__ import annotations

import asyncio
import logging
from contextlib import closing

from telebot import types
from telebot.async_telebot import AsyncTeleBot

from bot.delivery import deliver_answer, edit_status, send_status
from bot.media import batch_status_label, user_payload
from bot.queue import ChatWork, combine_user_contents, content_preview
from config import allowed_user_ids
from db import add_message, get_or_create_user, load_history, open_db
from llm.client import ChatClient

log = logging.getLogger(__name__)
_client = ChatClient()
_work = ChatWork()
_queue_notice: dict[int, int] = {}

START_TEXT = (
    "Привет. Это ИИ-бот.\n\n"
    "Пиши как в ChatGPT: текст, голос, картинки и файлы.\n"
    "/settings — модель, стиль, картинки\n"
    "/new — новый диалог"
)


def allowed(user_id: int) -> bool:
    ids = allowed_user_ids()
    return not ids or user_id in ids


async def clear_chat_queue(chat_id: int) -> None:
    await _work.clear_pending(chat_id)
    _queue_notice.pop(chat_id, None)


def _load_user(user_id: int) -> dict:
    with closing(open_db()) as conn:
        return dict(get_or_create_user(conn, user_id))


def _complete_sync(user_id: int, content, on_retry=None):
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
        on_retry=on_retry,
    )
    stored = content_preview(content)[:12000]
    with closing(open_db()) as conn:
        add_message(conn, user_id, thread_id, "user", stored)
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


async def _run_turn(tg: AsyncTeleBot, messages: list[types.Message]) -> None:
    first = messages[0]
    user = first.from_user
    chat_id = first.chat.id
    settings = await asyncio.to_thread(_load_user, user.id)
    try:
        await tg.send_chat_action(chat_id, "typing")
    except Exception:
        pass
    status = await send_status(tg, chat_id, batch_status_label(messages), first.message_id)
    try:
        payloads = []
        for item in messages:
            payloads.append(await user_payload(tg, item, settings["model"]))
        content = combine_user_contents(payloads)
    except Exception as exc:
        log.warning("payload failed error=%s", exc)
        await edit_status(tg, chat_id, status.message_id, str(exc)[:400])
        return
    loop = asyncio.get_running_loop()

    def on_retry(attempt, retries, code):
        asyncio.run_coroutine_threadsafe(
            edit_status(
                tg, chat_id, status.message_id,
                f"Ошибка API, повторяю ({attempt}/{retries})…",
            ),
            loop,
        )

    try:
        result = await asyncio.to_thread(_complete_sync, user.id, content, on_retry)
    except Exception:
        log.exception("chat failed")
        await edit_status(tg, chat_id, status.message_id, "Не получилось ответить. Попробуй ещё раз.")
        return
    await deliver_answer(
        tg, chat_id, status.message_id, result.text,
        images=result.images, files=result.files,
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
        content_types=["text", "voice", "audio", "photo", "document", "video_note"],
    )
    async def chat_cmd(message: types.Message) -> None:
        if message.text and message.text.startswith("/"):
            return
        user = message.from_user
        if user is None or not allowed(user.id):
            return
        log.info(
            "incoming chat_id=%s user_id=%s content=%s",
            message.chat.id, user.id, message.content_type,
        )
        state = await _work.submit(message.chat.id, message)
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
            batch = [message]
            while batch:
                await _clear_notice(tg, message.chat.id)
                await _run_turn(tg, batch)
                batch = await _work.finish_or_continue(message.chat.id)
        except Exception:
            log.exception("chat loop failed")
            await _work.abort(message.chat.id)
            try:
                await tg.send_message(message.chat.id, "Не получилось ответить. Попробуй ещё раз.")
            except Exception:
                pass
