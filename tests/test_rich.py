from bot.rich import PLAIN_LIMIT, fit, rich_message


def test_fit_keeps_short_text():
    assert fit("привет", 100) == "привет"


def test_fit_truncates_long_utf8():
    text = "а" * 5000
    trimmed = fit(text, PLAIN_LIMIT)
    assert trimmed.endswith("…")
    assert len(trimmed.encode("utf-8")) <= PLAIN_LIMIT


def test_rich_message_uses_markdown():
    message = rich_message("# Заголовок\n\nтекст")
    assert message.markdown.startswith("# Заголовок")
