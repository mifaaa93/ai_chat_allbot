from io import BytesIO
import zipfile

import pytest

from llm.archive import ZipError, build_zip, extract_zip


def test_build_and_extract_roundtrip():
    name, data = build_zip([("a.txt", b"hello"), ("dir/b.txt", b"world")])
    assert name == "archive.zip"
    members = dict(extract_zip(data))
    assert members["a.txt"] == b"hello"
    assert members["b.txt"] == b"world"


def test_extract_skips_macos_junk():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ok.txt", "yes")
        archive.writestr("__MACOSX/._ok.txt", "no")
        archive.writestr(".DS_Store", "no")
    members = dict(extract_zip(buffer.getvalue()))
    assert list(members) == ["ok.txt"]


def test_extract_rejects_oversize_member():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("big.txt", b"x" * 1_000_001)
    with pytest.raises(ZipError, match="слишком большой"):
        extract_zip(buffer.getvalue())


def test_extract_rejects_garbage():
    with pytest.raises(ZipError, match="не zip"):
        extract_zip(b"not-a-zip")