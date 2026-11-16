from llm.web import _allowed, html_to_text


def test_html_to_text_strips_tags():
    text = html_to_text("<html><script>x</script><p>Hello <b>world</b></p></html>")
    assert "Hello" in text
    assert "world" in text
    assert "script" not in text.lower() or "x" not in text


def test_allowed_blocks_localhost_and_file():
    assert _allowed("file:///etc/passwd")
    assert _allowed("http://localhost/admin")
    assert _allowed("https://example.com") is None
