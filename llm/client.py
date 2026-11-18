"""CheapVibeCode chat completions with retry and tool loop."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

import requests

from config import CHAT_TIMEOUT, CHAT_TIMEOUT_RETRIES, CVC_API_KEY, CVC_BASE_URL
from llm.tools import TOOLS, execute_tool
from models_catalog import clamp_reasoning, lower_reasoning

log = logging.getLogger(__name__)

RETRY_ATTEMPTS = 2
RATE_LIMIT_ATTEMPTS = 5
RETRY_DELAY = 2.0
RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_MAX_WAIT = 15.0
RATE_LIMIT_MAX_WAIT = 120.0
MAX_TOOL_ROUNDS = 6

SYSTEM_BASE = """Ты — умный ассистент в Telegram. Отвечай на языке пользователя.
Пиши Markdown: заголовки, списки, короткий код в блоках.
Длинный код, таблицы, конфиги, PDF и готовые документы отдавай инструментом write_file. Для PDF вызывай write_file с filename вроде hello.pdf и обычным текстом в content.
Несколько файлов или архив — write_zip: список files с filename и content, бот соберёт zip.
Картинки по запросу — generate_image. Альбом фото — это один запрос, смотри все кадры.
Если пользователь отвечает на сообщение, в запросе будет цитата и текст исходного сообщения — правь именно это.
Если приложено содержимое недавнего файла, правь его через write_file/write_zip с тем же именем, не выдумывай файл заново.
Актуальные факты из интернета — web_search, затем web_fetch по нужным ссылкам.
Не выдумывай содержимое страниц. Не упоминай названия инструментов.
Не пиши дисклеймеры про то, что ты модель. Будь конкретным."""

STYLE_HINTS = {
    "brief": "Отвечай коротко, без воды.",
    "code": "Если уместно, сразу давай рабочий код или файл.",
    "normal": "",
}


@dataclass
class OutFile:
    filename: str
    data: bytes
    source_text: str | None = None


@dataclass
class ChatResult:
    text: str
    images: list[bytes] = field(default_factory=list)
    image_prompts: list[str] = field(default_factory=list)
    files: list[OutFile] = field(default_factory=list)


def _status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    return _status(exc) in RETRY_STATUSES


def _effort_rejected(exc: BaseException) -> bool:
    if _status(exc) != 400:
        return False
    response = getattr(exc, "response", None)
    blob = (getattr(response, "text", None) or "").lower()
    return "reasoning" in blob or "effort" in blob


def _retry_wait(exc: BaseException, attempt: int) -> float:
    if _status(exc) == 429:
        header = _retry_after_seconds(exc)
        if header is not None:
            return min(max(header, 1.0), RATE_LIMIT_MAX_WAIT)
        return min(5.0 * (2 ** (attempt - 1)), 60.0)
    header = _retry_after_seconds(exc)
    if header is not None:
        return min(max(header, 1.0), RETRY_MAX_WAIT)
    return min(RETRY_DELAY * attempt, RETRY_MAX_WAIT)


def _retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    header = getattr(response, "headers", None) or {}
    raw = header.get("Retry-After") or header.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _retry_budget(exc: BaseException) -> int:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return CHAT_TIMEOUT_RETRIES
    if _status(exc) == 429:
        return RATE_LIMIT_ATTEMPTS
    return RETRY_ATTEMPTS


def _emit(callback, event: str, **payload) -> None:
    if callback is None:
        return
    try:
        callback(event, **payload)
    except Exception:
        log.exception("on_progress failed event=%s", event)


def build_system(style: str) -> str:
    hint = STYLE_HINTS.get(style, "")
    if hint:
        return SYSTEM_BASE + "\n" + hint
    return SYSTEM_BASE


class ChatClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or CVC_API_KEY
        self.base_url = (base_url or CVC_BASE_URL).rstrip("/")

    def complete(
        self,
        history: list[dict],
        user_message,
        model: str,
        reasoning: str = "off",
        style: str = "normal",
        image_quality: str = "low",
        on_retry=None,
        on_progress=None,
    ) -> ChatResult:
        messages = [{"role": "system", "content": build_system(style)}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        extras = ChatResult(text="")
        for _round in range(MAX_TOOL_ROUNDS):
            _emit(on_progress, "thinking")
            message = self._request(
                messages,
                model=model,
                reasoning=reasoning,
                on_retry=on_retry,
                on_progress=on_progress,
            )
            tool_calls = message.get("tool_calls") or []
            content = (message.get("content") or "").strip()
            if tool_calls:
                messages.append(message)
                for call in tool_calls:
                    name = call["function"]["name"]
                    raw_args = call["function"].get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {}
                    log.info("Tool %s", name)
                    _emit(on_progress, "tool", name=name, args=args)
                    result = execute_tool(name, args, image_quality=image_quality)
                    outfile = None
                    if result.image:
                        extras.images.append(result.image)
                        extras.image_prompts.append(result.image_prompt or "")
                    if result.file:
                        outfile = OutFile(
                            filename=result.file[0],
                            data=result.file[1],
                            source_text=result.source_text,
                        )
                        extras.files.append(outfile)
                    _emit(
                        on_progress,
                        "tool_done",
                        name=name,
                        args=args,
                        file=outfile,
                        image=result.image,
                        image_prompt=result.image_prompt or "",
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.get("id", name),
                        "content": result.text,
                    })
                continue
            extras.text = content or extras.text or "Готово."
            return extras
        extras.text = extras.text or "Слишком много шагов инструментов. Уточни запрос."
        return extras

    def _request(
        self,
        messages: list[dict],
        model: str,
        reasoning: str,
        on_retry=None,
        on_progress=None,
    ) -> dict:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.4,
            "tools": TOOLS,
            "tool_choice": "auto",
        }
        effort = clamp_reasoning(model, reasoning)
        if effort:
            payload["reasoning_effort"] = effort
            if effort != (reasoning or "").strip().lower():
                log.info("reasoning clamp model=%s want=%s send=%s", model, reasoning, effort)
        attempt = 1
        last_error: BaseException | None = None
        while True:
            started = time.monotonic()
            try:
                response = requests.post(
                    self.base_url + "/chat/completions",
                    headers={"Authorization": "Bearer " + self.api_key},
                    json=dict(payload),
                    timeout=CHAT_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as exc:
                last_error = exc
                if _effort_rejected(exc) and "reasoning_effort" in payload:
                    current = payload["reasoning_effort"]
                    nxt = lower_reasoning(current)
                    if nxt:
                        payload["reasoning_effort"] = nxt
                    else:
                        payload.pop("reasoning_effort", None)
                    log.warning("reasoning %s rejected for %s, send=%s", current, model, payload.get("reasoning_effort"))
                    continue
                budget = _retry_budget(exc)
                if not is_transient(exc) or attempt > budget:
                    log.exception("LLM failed elapsed=%.2fs attempt=%s", time.monotonic() - started, attempt)
                    raise
                wait = _retry_wait(exc, attempt)
                status = _status(exc)
                timeout = isinstance(exc, requests.Timeout)
                log.warning(
                    "LLM retry attempt=%s/%s wait=%.1fs status=%s timeout=%s",
                    attempt, budget, wait, status, timeout,
                )
                _emit(
                    on_progress,
                    "retry",
                    attempt=attempt,
                    budget=budget,
                    status=status,
                    timeout=timeout,
                )
                if on_retry:
                    on_retry(attempt, budget, status)
                time.sleep(wait)
                attempt += 1
                continue
            log.info("LLM ok elapsed=%.2fs", time.monotonic() - started)
            return data["choices"][0]["message"]
