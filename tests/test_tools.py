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


def test_write_zip_packs_two_text_files():
    result = execute_tool("write_zip", {
        "filename": "pack.zip",
        "files": [
            {"filename": "a.txt", "content": "один"},
            {"filename": "b.md", "content": "# два"},
        ],
    })
    assert result.file is not None
    name, data = result.file
    assert name == "pack.zip"
    assert data[:2] == b"PK"
    from io import BytesIO
    import zipfile
    with zipfile.ZipFile(BytesIO(data)) as archive:
        assert archive.read("a.txt") == "один".encode("utf-8")
        assert archive.read("b.md").startswith(b"#")


def test_write_zip_rejects_exe_member():
    result = execute_tool("write_zip", {
        "files": [{"filename": "a.exe", "content": "x"}],
    })
    assert result.file is None
    assert "Расширение" in result.text
