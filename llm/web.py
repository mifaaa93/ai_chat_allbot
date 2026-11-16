"""Fetch and search the web with curl_cffi Chrome TLS."""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from urllib.parse import quote_plus, urlparse

from config import WEB_TIMEOUT

log = logging.getLogger(__name__)

MAX_TEXT = 80_000
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


class _TextExtractor(HTMLParser):
    skip = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.skip:
            self._skip += 1
        if tag in {"p", "br", "li", "h1", "h2", "h3", "tr", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.skip and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = " ".join(data.split())
        if text:
            self.parts.append(text + " ")


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\n{3,}", "\n\n", "".join(parser.parts))
    return text.strip()[:MAX_TEXT]


def _allowed(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "Только http(s) URL."
    host = (parsed.hostname or "").lower()
    if not host or host in BLOCKED_HOSTS or host.endswith(".local"):
        return "Этот хост нельзя открывать."
    if host.startswith("10.") or host.startswith("192.168.") or host.startswith("172."):
        return "Приватные адреса закрыты."
    return None


def _session():
    from curl_cffi.requests import Session

    return Session(impersonate="chrome")


def fetch_url(url: str) -> str:
    url = (url or "").strip()
    reason = _allowed(url)
    if reason:
        return reason
    try:
        with _session() as session:
            response = session.get(
                url,
                timeout=WEB_TIMEOUT,
                allow_redirects=True,
                headers={"Accept-Language": "ru,en;q=0.8"},
            )
    except Exception as exc:
        log.info("web_fetch failed %s", type(exc).__name__)
        return "Не удалось открыть страницу."
    if response.status_code >= 400:
        return f"Страница ответила HTTP {response.status_code}."
    content_type = (response.headers.get("content-type") or "").lower()
    body = response.text or ""
    if "html" in content_type or "<html" in body[:200].lower():
        text = html_to_text(body)
    else:
        text = body[:MAX_TEXT]
    if not text.strip():
        return "Страница пустая."
    return f"URL: {url}\n\n{text}"


def search_web(query: str) -> str:
    query = " ".join((query or "").split())
    if not query:
        return "Пустой запрос."
    url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
    try:
        with _session() as session:
            response = session.get(url, timeout=WEB_TIMEOUT, allow_redirects=True)
    except Exception as exc:
        log.info("web_search failed %s", type(exc).__name__)
        return "Поиск недоступен."
    if response.status_code >= 400:
        return f"Поиск ответил HTTP {response.status_code}."
    html = response.text or ""
    titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, flags=re.I | re.S)
    links = re.findall(r'class="result__url"[^>]*href="([^"]+)"', html, flags=re.I)
    if not links:
        links = re.findall(r'uddg=([^"&]+)', html)
    clean_titles = [html_to_text(item) for item in titles]
    lines = []
    for index, title in enumerate(clean_titles[:5], start=1):
        href = links[index - 1] if index - 1 < len(links) else ""
        lines.append(f"{index}. {title}\n{href}")
    if not lines:
        text = html_to_text(html)
        return text[:4000] or "Ничего не нашлось."
    return "Результаты поиска:\n" + "\n".join(lines)
