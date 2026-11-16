from types import SimpleNamespace

from bot.media import status_label


def test_voice_status_label():
    message = SimpleNamespace(
        voice=object(),
        audio=None,
        video_note=None,
        photo=None,
        document=None,
    )
    assert status_label(message) == "Слушаю голос…"
