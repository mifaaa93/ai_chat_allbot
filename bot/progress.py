"""Live status text while a turn is running."""

from __future__ import annotations

import time

HEARTBEAT_MIN_ELAPSED = 8


def format_elapsed(seconds: int) -> str:
    return f"{max(0, int(seconds))}с"


def compose_status(label: str, elapsed: int, min_elapsed: int = HEARTBEAT_MIN_ELAPSED) -> str:
    text = (label or "Думаю…").strip() or "Думаю…"
    if elapsed < min_elapsed:
        return text
    base = text.rstrip("…").rstrip()
    return f"{base} {format_elapsed(elapsed)}"


def tool_label(name: str, args: dict | None = None) -> str:
    args = args or {}
    if name == "write_file":
        return f"Пишу файл {_filename(args, 'файл')}…"
    if name == "write_zip":
        return f"Собираю архив {_filename(args, 'archive.zip')}…"
    if name == "web_search":
        query = str(args.get("query") or "").strip()
        if not query:
            return "Ищу в интернете…"
        short = query if len(query) <= 60 else query[:57] + "…"
        return f"Ищу: {short}…"
    if name == "web_fetch":
        return "Читаю страницу…"
    if name == "generate_image":
        return "Рисую картинку…"
    return "Работаю…"


def tool_done_label(name: str, args: dict | None = None, sent: bool = False) -> str:
    args = args or {}
    if name == "write_file":
        filename = _filename(args, "файл")
        if sent:
            return f"Файл {filename} отправлен, собираю ответ…"
        return f"Файл {filename} готов, собираю ответ…"
    if name == "write_zip":
        filename = _filename(args, "archive.zip")
        if sent:
            return f"Архив {filename} отправлен, собираю ответ…"
        return f"Архив {filename} готов, собираю ответ…"
    if name == "generate_image":
        if sent:
            return "Картинка отправлена, собираю ответ…"
        return "Картинка готова, собираю ответ…"
    if name == "web_search":
        return "Нашёл источники, собираю ответ…"
    if name == "web_fetch":
        return "Страница прочитана, собираю ответ…"
    return "Собираю ответ…"


def retry_label(attempt: int, budget: int, status: int | None, timeout: bool = False) -> str:
    if timeout or status is None:
        return "Провайдер думает слишком долго, пробую ещё раз…"
    return f"Ошибка API, повторяю ({attempt}/{budget})…"


def _filename(args: dict, fallback: str) -> str:
    name = str(args.get("filename") or "").replace("\\", "/").split("/")[-1].strip()
    return name or fallback


class TurnStatus:
    def __init__(self, label: str = "Думаю…"):
        self.label = label
        self.started = time.monotonic()
        self.used_tools = False

    def elapsed(self) -> int:
        return int(time.monotonic() - self.started)

    def text(self) -> str:
        return compose_status(self.label, self.elapsed())

    def set_label(self, label: str, *, restart: bool = False) -> None:
        self.label = label
        if restart:
            self.started = time.monotonic()
