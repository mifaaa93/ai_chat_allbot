"""Model tools: web, images, files."""

from __future__ import annotations

import json
from dataclasses import dataclass

from llm.archive import ZipError, build_zip
from llm.images import generate_image
from llm.pdf import render_pdf
from llm.web import fetch_url, search_web

ALLOWED_FILE_EXT = {
    ".txt", ".md", ".csv", ".json", ".py", ".html", ".xml", ".yaml", ".yml", ".log", ".pdf",
}
MAX_FILE_BYTES = 1_000_000
ALLOWED_HINT = "txt/md/csv/json/py/html/xml/yaml/log/pdf"


@dataclass
class ToolResult:
    text: str
    image: bytes | None = None
    file: tuple[str, bytes] | None = None


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Поиск в интернете. Верни запрос на языке пользователя.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Скачать страницу по http(s) URL и вернуть текст.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Сгенерировать изображение по текстовому описанию.",
            "parameters": {
                "type": "object",
                "properties": {"prompt": {"type": "string"}},
                "required": ["prompt"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Собрать один файл и отдать пользователю в Telegram. Для PDF передай filename с .pdf и обычный текст в content — бот сам соберёт PDF. Несколько файлов клади в write_zip.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["filename", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_zip",
            "description": "Собрать zip-архив из нескольких файлов и отдать пользователю. Используй, когда файлов больше одного или пользователь просит архив/zip.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Имя архива, например docs.zip",
                    },
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["filename", "content"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["files"],
                "additionalProperties": False,
            },
        },
    },
]


def execute_tool(name: str, args: dict, image_quality: str = "low") -> ToolResult:
    if name == "web_search":
        return ToolResult(text=search_web(str(args.get("query") or "")))
    if name == "web_fetch":
        return ToolResult(text=fetch_url(str(args.get("url") or "")))
    if name == "generate_image":
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(text="Пустой prompt.")
        image = generate_image(prompt, quality=image_quality)
        return ToolResult(text="Изображение сгенерировано и будет отправлено пользователю.", image=image)
    if name == "write_file":
        return _write_file(str(args.get("filename") or "file.txt"), str(args.get("content") or ""))
    if name == "write_zip":
        return _write_zip(args)
    return ToolResult(text=f"Неизвестный инструмент {name}.")


def _write_file(filename: str, content: str) -> ToolResult:
    encoded = _encode_member(filename, content)
    if encoded.file is None:
        return encoded
    name, _data = encoded.file
    return ToolResult(text=f"Файл {name} будет отправлен пользователю.", file=encoded.file)


def _write_zip(args: dict) -> ToolResult:
    filename = str(args.get("filename") or "archive.zip")
    raw_files = args.get("files") or []
    if isinstance(raw_files, str):
        try:
            raw_files = json.loads(raw_files)
        except json.JSONDecodeError:
            return ToolResult(text="Не разобрал список файлов для архива.")
    if not isinstance(raw_files, list) or not raw_files:
        return ToolResult(text="Для zip нужен список files.")
    members: list[tuple[str, bytes]] = []
    for item in raw_files:
        if not isinstance(item, dict):
            return ToolResult(text="Каждый файл в zip — объект с filename и content.")
        encoded = _encode_member(str(item.get("filename") or "file.txt"), str(item.get("content") or ""))
        if encoded.file is None:
            return encoded
        members.append(encoded.file)
    try:
        archive = build_zip(members, filename)
    except ZipError as exc:
        return ToolResult(text=str(exc))
    return ToolResult(text=f"Архив {archive[0]} будет отправлен пользователю.", file=archive)


def _encode_member(filename: str, content: str) -> ToolResult:
    name = filename.replace("\\", "/").split("/")[-1].strip() or "file.txt"
    if "." not in name:
        name += ".txt"
    ext = "." + name.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_FILE_EXT:
        return ToolResult(text=f"Расширение {ext} нельзя отправить. Используй {ALLOWED_HINT}.")
    if not content.strip():
        return ToolResult(text=f"Пустой файл {name}.")
    if ext == ".pdf":
        try:
            data = render_pdf(content, title=name)
        except Exception as exc:
            return ToolResult(text=f"Не собрал PDF: {exc}")
    else:
        data = content.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        return ToolResult(text=f"Файл {name} больше 1 МБ, укороти содержимое.")
    return ToolResult(text="ok", file=(name, data))
