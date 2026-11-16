"""CheapVibeCode Telegram chatter."""

from __future__ import annotations

import asyncio
import logging

import telebot
from telebot.async_telebot import AsyncTeleBot

from bot.handlers_chat import register as register_chat
from bot.handlers_settings import register as register_settings
from config import TELEGRAM_BOT_TOKEN, configure_logging, require_secrets
from db import init_db
from models_catalog import refresh_catalog

log = logging.getLogger("allbot")

COMMANDS = [
    telebot.types.BotCommand("start", "Начать чат"),
    telebot.types.BotCommand("help", "Что умеет бот"),
    telebot.types.BotCommand("settings", "Модель и настройки"),
    telebot.types.BotCommand("new", "Новый диалог"),
]


class _HandlerErrors(telebot.ExceptionHandler):
    def handle(self, exception) -> bool:
        log.exception("telegram handler crashed", exc_info=exception)
        return True


def create_bot() -> AsyncTeleBot:
    tg = AsyncTeleBot(
        TELEGRAM_BOT_TOKEN,
        parse_mode=None,
        disable_web_page_preview=True,
        exception_handler=_HandlerErrors(),
    )
    register_settings(tg)
    register_chat(tg)
    return tg


async def set_commands(tg: AsyncTeleBot) -> None:
    await tg.set_my_commands(COMMANDS)
    log.info("Bot commands registered: %s", ", ".join(item.command for item in COMMANDS))


async def main() -> None:
    configure_logging()
    require_secrets()
    init_db()
    refresh_catalog()
    tg = create_bot()
    me = await tg.get_me()
    await set_commands(tg)
    log.info("Bot @%s started", me.username)
    await tg.infinity_polling(skip_pending=True, timeout=60, request_timeout=90)


if __name__ == "__main__":
    asyncio.run(main())
