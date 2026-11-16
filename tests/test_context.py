from types import SimpleNamespace

from bot.context import format_reply, looks_like_file_edit, merge_content, select_files


def test_format_reply_includes_quote_and_body():
    quoted = SimpleNamespace(text="только эту фразу")
    reply = SimpleNamespace(
        text="полный текст сообщения про отчёт",
        caption=None,
        document=SimpleNamespace(file_name="report.pdf", file_id="fid"),
        photo=None,
        voice=None,
        audio=None,
        video=None,
        video_note=None,
        message_id=55,
    )
    message = SimpleNamespace(reply_to_message=reply, quote=quoted)
    text = format_reply(message)
    assert "Цитата:" in text
    assert "только эту фразу" in text
    assert "полный текст сообщения про отчёт" in text
    assert "report.pdf" in text
    assert "message_id=55" in text


def test_format_reply_without_quote_uses_message_text():
    reply = SimpleNamespace(
        text="привет",
        caption=None,
        document=None,
        photo=None,
        voice=None,
        audio=None,
        video=None,
        video_note=None,
        message_id=1,
    )
    message = SimpleNamespace(reply_to_message=reply, quote=None)
    text = format_reply(message)
    assert "привет" in text
    assert "Цитата:" not in text


def test_select_files_by_reply_message_id():
    reply = SimpleNamespace(message_id=10, document=None, photo=None)
    message = SimpleNamespace(reply_to_message=reply, quote=None)
    files = [
        {"tg_file_id": "a", "filename": "old.txt", "tg_message_id": 9, "anchor_message_id": 8, "origin": "bot", "kind": "document"},
        {"tg_file_id": "b", "filename": "notes.txt", "tg_message_id": 11, "anchor_message_id": 10, "origin": "bot", "kind": "document"},
    ]
    chosen = select_files("поправь", files, message, skip_ids=set())
    assert [row["filename"] for row in chosen] == ["notes.txt"]


def test_select_files_by_name_and_skips_current_upload():
    files = [
        {"tg_file_id": "keep", "filename": "a.py", "origin": "bot", "kind": "document", "tg_message_id": 1, "anchor_message_id": 1},
        {"tg_file_id": "skip", "filename": "b.py", "origin": "bot", "kind": "document", "tg_message_id": 2, "anchor_message_id": 2},
    ]
    chosen = select_files("поправь a.py", files, None, skip_ids={"skip"})
    assert [row["tg_file_id"] for row in chosen] == ["keep"]


def test_looks_like_file_edit():
    assert looks_like_file_edit("поправь опечатку")
    assert looks_like_file_edit("сделай zip")
    assert not looks_like_file_edit("привет, как дела?")


def test_merge_content_prepends_text():
    assert merge_content("цитата", ["файл"], "вопрос") == "цитата\n\nфайл\n\nвопрос"
