from bot.progress import (
    TurnStatus,
    compose_status,
    format_elapsed,
    retry_label,
    tool_done_label,
    tool_label,
)


def test_format_elapsed():
    assert format_elapsed(8) == "8с"
    assert format_elapsed(16) == "16с"
    assert format_elapsed(80) == "80с"


def test_compose_status_hides_short_wait():
    assert compose_status("Думаю…", 3) == "Думаю…"
    assert compose_status("Думаю…", 8) == "Думаю 8с"
    assert compose_status("Думаю…", 16) == "Думаю 16с"


def test_tool_labels():
    assert tool_label("write_file", {"filename": "spec.md"}) == "Пишу файл spec.md…"
    assert "archive.zip" in tool_label("write_zip", {})
    assert tool_label("web_search", {"query": "usdt rewards"}) == "Ищу: usdt rewards…"
    assert tool_label("web_fetch", {}) == "Читаю страницу…"
    assert tool_label("generate_image", {}) == "Рисую картинку…"


def test_tool_done_and_retry_labels():
    assert "отправлен" in tool_done_label("write_file", {"filename": "a.md"}, sent=True)
    assert "готов" in tool_done_label("write_file", {"filename": "a.md"}, sent=False)
    assert "слишком долго" in retry_label(1, 1, None, timeout=True)
    assert "1/5" in retry_label(1, 5, 429)


def test_turn_status_elapsed():
    clock = TurnStatus("Думаю…")
    clock.started = clock.started - 20
    assert clock.text() == "Думаю 20с"
    clock.set_label("Пишу файл a.md…")
    assert clock.text().startswith("Пишу файл a.md")
    clock.set_label("Думаю…", restart=True)
    assert clock.text() == "Думаю…"
    assert clock.elapsed() < 2
