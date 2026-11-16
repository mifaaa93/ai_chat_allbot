import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.media import album_payload, batch_status_label, status_label, zip_to_content
from llm.archive import build_zip


def test_voice_status_label():
    message = SimpleNamespace(
        voice=object(),
        audio=None,
        video_note=None,
        photo=None,
        document=None,
    )
    assert status_label(message) == "Слушаю голос…"


def test_album_status_label():
    photo = SimpleNamespace(
        voice=None, audio=None, video_note=None, photo=object(), document=None, media_group_id="g",
    )
    assert "альбом" in batch_status_label([photo, photo]).lower()


def test_zip_to_content_reads_text():
    _name, data = build_zip([("note.txt", "привет".encode("utf-8"))])
    text = zip_to_content(data, "note.zip", "посмотри", "gpt-6-luna")
    assert "посмотри" in text
    assert "привет" in text


def test_album_payload_one_caption_all_photos():
    async def scenario():
        first = SimpleNamespace(
            caption="что на фото",
            text=None,
            photo=[SimpleNamespace(file_id="a")],
            document=None,
            video=None,
            video_note=None,
            media_group_id="g",
        )
        second = SimpleNamespace(
            caption=None,
            text=None,
            photo=[SimpleNamespace(file_id="b")],
            document=None,
            video=None,
            video_note=None,
            media_group_id="g",
        )
        tg = AsyncMock()
        with patch("bot.media.download_file", new=AsyncMock(side_effect=[
            (b"img-a", "a.jpg"),
            (b"img-b", "b.jpg"),
        ])):
            with patch("bot.media.supports_vision", return_value=True):
                content = await album_payload(tg, [first, second], "gpt-6-luna")
        assert isinstance(content, list)
        texts = [part["text"] for part in content if part.get("type") == "text"]
        assert any("что на фото" in item for item in texts)
        assert sum(part.get("type") == "image_url" for part in content) == 2
        assert "Опиши изображение" not in "".join(texts)

    asyncio.run(scenario())
