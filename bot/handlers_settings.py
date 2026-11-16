"""Settings menus: model, reasoning, style, image quality, new chat."""

from __future__ import annotations

import asyncio
from contextlib import closing

from telebot import types
from telebot.async_telebot import AsyncTeleBot

from bot.handlers_chat import clear_chat_queue
from db import get_or_create_user, new_thread, open_db, update_user
from models_catalog import (
    GROUPS, IMAGE_QUALITY, STYLES,
    capabilities_line, format_context, format_multiplier, format_reasoning_label,
    get_model, group_title, model_button_label, models_in_group, reasoning_menu,
    refresh_catalog, supports_reasoning, title_for,
)


def settings_text(user) -> str:
    info = get_model(user["model"])
    title = title_for(user["model"])
    if info is not None:
        model_line = f"Модель: {title} {format_multiplier(info.multiplier)}"
        ctx = f"Контекст: {format_context(info.context)}"
        if info.max_output:
            ctx += f" · выход {format_context(info.max_output)}"
        caps = f"Возможности: {capabilities_line(info)}"
        reason = f"Reasoning: {format_reasoning_label(user['model'], user['reasoning'])}"
    else:
        model_line = f"Модель: {title}"
        ctx = "Контекст: ?"
        caps = "Возможности: ?"
        reason = f"Reasoning: {format_reasoning_label(user['model'], user['reasoning'])}"
    return (
        f"{model_line}\n"
        f"{ctx}\n"
        f"{caps}\n"
        f"{reason}\n"
        f"Стиль: {STYLES.get(user['style'], user['style'])}\n"
        f"Картинки: {IMAGE_QUALITY.get(user['image_quality'], user['image_quality'])}\n\n"
        "Выбери, что поменять."
    )


def root_markup(user=None) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("Модель", callback_data="s:models"),
        types.InlineKeyboardButton("Новый чат", callback_data="s:new"),
    )
    extras = [
        types.InlineKeyboardButton("Стиль", callback_data="s:style"),
        types.InlineKeyboardButton("Картинки", callback_data="s:iq"),
    ]
    if user is None or supports_reasoning(user["model"]):
        extras.insert(0, types.InlineKeyboardButton("Reasoning", callback_data="s:reason"))
    markup.row(*extras)
    return markup


def groups_markup() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    for group in GROUPS:
        count = len(models_in_group(group))
        if not count:
            continue
        markup.add(
            types.InlineKeyboardButton(
                f"{group_title(group)} · {count}",
                callback_data=f"s:g:{group}",
            )
        )
    markup.add(types.InlineKeyboardButton("Назад", callback_data="s:root"))
    return markup


def models_markup(group: str) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    for item in models_in_group(group):
        markup.add(
            types.InlineKeyboardButton(
                model_button_label(item),
                callback_data=f"s:m:{item.model_id}",
            )
        )
    markup.add(types.InlineKeyboardButton("Назад", callback_data="s:models"))
    return markup


def choice_markup(prefix: str, options: dict[str, str]) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    row = []
    for key, title in options.items():
        row.append(types.InlineKeyboardButton(title, callback_data=f"s:{prefix}:{key}"))
        if len(row) == 3:
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)
    markup.add(types.InlineKeyboardButton("Назад", callback_data="s:root"))
    return markup


def _settings_user(user_id: int):
    with closing(open_db()) as conn:
        return get_or_create_user(conn, user_id)


def _new_thread_sync(user_id: int):
    with closing(open_db()) as conn:
        return new_thread(conn, user_id)


def _apply_settings(user_id: int, data: str):
    with closing(open_db()) as conn:
        user = get_or_create_user(conn, user_id)
        text = settings_text(user)
        markup = root_markup(user)
        if data == "s:root":
            pass
        elif data == "s:new":
            user = new_thread(conn, user_id)
            text = "Новый диалог. История сброшена.\n\n" + settings_text(user)
            markup = root_markup(user)
        elif data == "s:models":
            refresh_catalog()
            text = "Группа моделей:"
            markup = groups_markup()
        elif data.startswith("s:g:"):
            group = data[4:]
            text = f"Модели: {group_title(group)}"
            markup = models_markup(group)
        elif data.startswith("s:m:"):
            model_id = data[4:]
            user = update_user(conn, user_id, model=model_id)
            text = "Модель: " + title_for(model_id) + "\n\n" + settings_text(user)
            markup = root_markup(user)
        elif data == "s:reason":
            if supports_reasoning(user["model"]):
                text = (
                    "Глубина reasoning для этой модели.\n"
                    "Чем выше, тем дольше и дороже. Недоступный уровень заменяется ближайшим."
                )
                markup = choice_markup("r", reasoning_menu(user["model"]))
            else:
                text = "Эта модель не поддерживает reasoning.\n\n" + settings_text(user)
        elif data.startswith("s:r:"):
            level = data[4:]
            if level in reasoning_menu(user["model"]):
                user = update_user(conn, user_id, reasoning=level)
            text = settings_text(user)
            markup = root_markup(user)
        elif data == "s:style":
            text = "Стиль ответов:"
            markup = choice_markup("st", STYLES)
        elif data.startswith("s:st:"):
            user = update_user(conn, user_id, style=data[5:])
            text = settings_text(user)
            markup = root_markup(user)
        elif data == "s:iq":
            text = "Качество картинок:"
            markup = choice_markup("q", IMAGE_QUALITY)
        elif data.startswith("s:q:"):
            user = update_user(conn, user_id, image_quality=data[4:])
            text = settings_text(user)
            markup = root_markup(user)
        return text, markup, data == "s:new"


def register(tg: AsyncTeleBot) -> None:
    @tg.message_handler(commands=["settings"])
    async def settings_cmd(message: types.Message) -> None:
        await asyncio.to_thread(refresh_catalog)
        user = await asyncio.to_thread(_settings_user, message.from_user.id)
        await tg.send_message(message.chat.id, settings_text(user), reply_markup=root_markup(user))

    @tg.message_handler(commands=["new"])
    async def new_cmd(message: types.Message) -> None:
        await clear_chat_queue(message.chat.id)
        await asyncio.to_thread(_new_thread_sync, message.from_user.id)
        await tg.send_message(message.chat.id, "Новый диалог. История сброшена.")

    @tg.callback_query_handler(func=lambda call: (call.data or "").startswith("s:"))
    async def settings_cb(call: types.CallbackQuery) -> None:
        data = call.data or ""
        user_id = call.from_user.id
        text, markup, reset = await asyncio.to_thread(_apply_settings, user_id, data)
        if reset:
            await clear_chat_queue(call.message.chat.id)
        try:
            await tg.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass
        await tg.answer_callback_query(call.id)
