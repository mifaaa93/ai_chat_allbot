"""Build a simple Unicode PDF from text."""

from __future__ import annotations

import html
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

FONT_NAME = "AllbotSans"
_FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\arial.ttf"),
    Path(r"C:\Windows\Fonts\calibri.ttf"),
    Path(r"C:\Windows\Fonts\segoeui.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
)


@lru_cache(maxsize=1)
def _font_path() -> Path:
    for path in _FONT_CANDIDATES:
        if path.is_file():
            pdfmetrics.registerFont(TTFont(FONT_NAME, str(path)))
            return path
    raise RuntimeError("Не найден TTF-шрифт с кириллицей.")


def render_pdf(text: str, title: str | None = None) -> bytes:
    _font_path()
    body = (text or "").strip()
    if not body:
        raise ValueError("Пустой текст.")
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=title or "Документ",
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    style = ParagraphStyle(
        "Body",
        fontName=FONT_NAME,
        fontSize=14,
        leading=20,
    )
    story = []
    for block in body.split("\n\n"):
        chunk = html.escape(block.strip(), quote=False).replace("\n", "<br/>")
        if chunk:
            story.append(Paragraph(chunk, style))
            story.append(Spacer(1, 8))
    if not story:
        raise ValueError("Пустой текст.")
    doc.build(story)
    data = buffer.getvalue()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("PDF не собрался.")
    return data
