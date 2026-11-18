import asyncio
from unittest.mock import AsyncMock

from telebot.asyncio_helper import ApiTelegramException

from bot.delivery import edit_status, send_status


def _tg_error():
    return ApiTelegramException(
        "editMessageText",
        None,
        {"error_code": 400, "description": "Bad Request: message is not modified"},
    )


def test_edit_status_ignores_async_not_modified():
    tg = AsyncMock()
    tg.edit_message_text.side_effect = _tg_error()
    asyncio.run(edit_status(tg, 1, 2, "Думаю…"))


def test_send_status_retries_without_reply():
    tg = AsyncMock()
    tg.send_message.side_effect = [_tg_error(), AsyncMock(message_id=9)]
    sent = asyncio.run(send_status(tg, 1, "Думаю…", reply_to=5))
    assert sent.message_id == 9
    assert tg.send_message.await_count == 2
