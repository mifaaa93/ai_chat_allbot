import asyncio
from types import SimpleNamespace

from bot.media import batch_status_label, status_label
from bot.queue import ChatWork, combine_user_contents, content_preview


def test_combine_single_passthrough():
    assert combine_user_contents(["только это"]) == "только это"


def test_combine_multiple_texts():
    text = combine_user_contents(["первый", "второй"])
    assert "ещё 2 сообщений" in text
    assert "1. первый" in text
    assert "2. второй" in text


def test_combine_mixed_keeps_images():
    vision = [{"type": "text", "text": "что на фото"}, {"type": "image_url", "image_url": {"url": "data:x"}}]
    parts = combine_user_contents(["подпись", vision])
    assert isinstance(parts, list)
    assert parts[0]["type"] == "text"
    assert any(part.get("type") == "image_url" for part in parts)


def test_content_preview_from_parts():
    assert content_preview([{"type": "text", "text": "а"}, {"type": "image_url"}]) == "а"


def test_chat_work_queues_while_busy():
    work = ChatWork(limit=2)

    async def scenario():
        first = SimpleNamespace(text="a")
        extra = SimpleNamespace(text="b")
        extra2 = SimpleNamespace(text="c")
        overflow = SimpleNamespace(text="d")
        assert await work.submit(1, first) == "run"
        assert await work.submit(1, extra) == "queued"
        assert await work.submit(1, extra2) == "queued"
        assert await work.pending_count(1) == 2
        assert await work.submit(1, overflow) == "full"
        batch = await work.finish_or_continue(1)
        assert batch == [extra, extra2]
        assert await work.finish_or_continue(1) == []
        assert await work.submit(1, first) == "run"

    asyncio.run(scenario())


def test_batch_status_for_several_texts():
    message = SimpleNamespace(voice=None, audio=None, video_note=None, photo=None, document=None)
    assert status_label(message) == "Думаю…"
    assert "2" in batch_status_label([message, message])
