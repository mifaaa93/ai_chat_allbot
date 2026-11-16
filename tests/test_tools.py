from llm.tools import execute_tool


def test_write_file_accepts_python():
    result = execute_tool("write_file", {"filename": "hello.py", "content": "print(1)\n"})
    assert result.file is not None
    assert result.file[0] == "hello.py"
    assert result.file[1].startswith(b"print")


def test_write_file_rejects_exe():
    result = execute_tool("write_file", {"filename": "a.exe", "content": "x"})
    assert result.file is None
    assert "Расширение" in result.text


def test_write_file_builds_cyrillic_pdf():
    result = execute_tool("write_file", {"filename": "hello.pdf", "content": "Привет, Мир"})
    assert result.file is not None
    name, data = result.file
    assert name == "hello.pdf"
    assert data.startswith(b"%PDF")
    assert len(data) > 500
