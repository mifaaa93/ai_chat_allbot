"""Load settings from the ignored .env file."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CVC_API_KEY = os.getenv("CVC_API_KEY", "").strip()
CVC_BASE_URL = os.getenv("CVC_BASE_URL", "https://ru.cheapvibecode.ru/v1").strip().rstrip("/")
CVC_MODEL = os.getenv("CVC_MODEL", "gpt-6-luna").strip()
CVC_IMAGE_MODEL = os.getenv("CVC_IMAGE_MODEL", "gpt-image-2.5-flare").strip()
CVC_TRANSCRIBE_MODEL = os.getenv("CVC_TRANSCRIBE_MODEL", "codex-transcribe").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/bot.sqlite3")
MODELS_CACHE_PATH = os.getenv("MODELS_CACHE_PATH", "data/models_cache.json")
CATALOG_TTL_SECONDS = max(60, int(os.getenv("CATALOG_TTL_SECONDS", "3600")))
LOG_PATH = os.getenv("LOG_PATH") or str(Path(DATABASE_PATH).expanduser().resolve().with_name("bot.log"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
HISTORY_LIMIT = 24
CHAT_TIMEOUT = 120
STT_TIMEOUT = 60
IMAGE_TIMEOUT = 180
WEB_TIMEOUT = 20
MAX_PENDING_PER_CHAT = max(1, int(os.getenv("MAX_PENDING_PER_CHAT", "8")))
ALBUM_WAIT_SECONDS = max(0.2, float(os.getenv("ALBUM_WAIT_SECONDS", "0.8")))
MAX_STORED_FILES = max(1, int(os.getenv("MAX_STORED_FILES", "20")))
SOURCE_TEXT_LIMIT = 80_000

_LOGGING_CONFIGURED = False


def allowed_user_ids() -> set[int]:
    return {
        int(item.strip())
        for item in os.getenv("ALLOWED_USER_IDS", "").split(",")
        if item.strip()
    }


def require_secrets() -> None:
    missing = [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
            ("CVC_API_KEY", CVC_API_KEY),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("Set " + ", ".join(missing) + " in .env")


def configure_logging() -> Path:
    global _LOGGING_CONFIGURED
    path = Path(LOG_PATH).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    root = logging.getLogger()
    if _LOGGING_CONFIGURED:
        root.setLevel(level)
        return path
    root.setLevel(level)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)
    file_handler = RotatingFileHandler(
        path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    _LOGGING_CONFIGURED = True
    logging.getLogger(__name__).info("Logging to %s", path)
    return path
