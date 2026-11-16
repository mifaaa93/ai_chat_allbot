"""Zip archives: build for sending, extract user uploads safely."""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

SKIP_NAMES = {".ds_store", "thumbs.db"}
MAX_ENTRIES = 40
MAX_UNCOMPRESSED = 8_000_000
MAX_MEMBER_BYTES = 1_000_000
MAX_ARCHIVE_BYTES = 10_000_000


class ZipError(RuntimeError):
    pass


def safe_name(filename: str) -> str:
    name = (filename or "").replace("\\", "/").split("/")[-1].strip()
    if name.startswith("."):
        name = name.lstrip(".")
    return name or "file.txt"


def build_zip(files: list[tuple[str, bytes]], filename: str = "archive.zip") -> tuple[str, bytes]:
    if not files:
        raise ZipError("Архив пустой.")
    if len(files) > MAX_ENTRIES:
        raise ZipError(f"В архиве больше {MAX_ENTRIES} файлов.")
    name = safe_name(filename)
    if not name.lower().endswith(".zip"):
        name += ".zip"
    buffer = BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for raw_name, payload in files:
            member = safe_name(raw_name)
            if member.lower() in used:
                stem = Path(member).stem
                suffix = Path(member).suffix
                index = 2
                while f"{stem}-{index}{suffix}".lower() in used:
                    index += 1
                member = f"{stem}-{index}{suffix}"
            used.add(member.lower())
            archive.writestr(member, payload)
    data = buffer.getvalue()
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ZipError("Архив больше 10 МБ, укороти содержимое.")
    return name, data


def _skip_member(filename: str) -> bool:
    parts = filename.replace("\\", "/").split("/")
    if any(part == "__MACOSX" for part in parts):
        return True
    name = (parts[-1] if parts else "").lower()
    return name in SKIP_NAMES or name.startswith("._")


def extract_zip(data: bytes) -> list[tuple[str, bytes]]:
    if not data:
        raise ZipError("Архив пустой.")
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ZipError("Это не zip-архив.") from exc
    with archive:
        infos = [item for item in archive.infolist() if not item.is_dir()]
        members: list[tuple[str, bytes]] = []
        total = 0
        for item in infos:
            if _skip_member(item.filename):
                continue
            member = safe_name(item.filename)
            if item.file_size > MAX_MEMBER_BYTES:
                raise ZipError(f"Файл {member} в архиве слишком большой.")
            total += item.file_size
            if total > MAX_UNCOMPRESSED:
                raise ZipError("Архив слишком большой после распаковки.")
            if len(members) >= MAX_ENTRIES:
                raise ZipError(f"В архиве больше {MAX_ENTRIES} файлов.")
            payload = archive.read(item)
            if len(payload) > MAX_MEMBER_BYTES:
                raise ZipError(f"Файл {member} в архиве слишком большой.")
            members.append((member, payload))
    if not members:
        raise ZipError("Архив пустой.")
    return members
