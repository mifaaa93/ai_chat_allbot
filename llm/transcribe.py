"""Telegram voice to text via Groq Whisper, with CheapVibeCode as fallback."""

from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from pathlib import Path

import requests

from config import (
    CVC_API_KEY, CVC_BASE_URL, CVC_TRANSCRIBE_MODEL, FFMPEG_BIN,
    GROQ_API_KEY, GROQ_BASE_URL, GROQ_TRANSCRIBE_MODEL,
    STT_RATE_LIMIT_ATTEMPTS, STT_RETRIES, STT_TIMEOUT,
)

log = logging.getLogger(__name__)


class Transcriber:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None):
        if api_key is None and GROQ_API_KEY:
            self.provider = "groq"
            self.api_key = GROQ_API_KEY
            self.base_url = (base_url or GROQ_BASE_URL).rstrip("/")
            self.model = model or GROQ_TRANSCRIBE_MODEL
        else:
            self.provider = "cvc"
            self.api_key = api_key or CVC_API_KEY
            self.base_url = (base_url or CVC_BASE_URL).rstrip("/")
            self.model = model or CVC_TRANSCRIBE_MODEL
        self.ffmpeg_bin = FFMPEG_BIN
        if self.ffmpeg_bin == "ffmpeg":
            try:
                import imageio_ffmpeg

                self.ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
            except (ImportError, RuntimeError):
                pass

    def convert_to_wav(self, audio: bytes, suffix: str = ".oga") -> bytes:
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="tg-voice-") as folder:
            source = Path(folder) / f"input{suffix}"
            target = Path(folder) / "converted.wav"
            source.write_bytes(audio)
            try:
                subprocess.run(
                    [
                        self.ffmpeg_bin, "-hide_banner", "-loglevel", "error",
                        "-y", "-i", str(source),
                        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                        str(target),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
            except FileNotFoundError as exc:
                raise RuntimeError("ffmpeg не найден.") from exc
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Конвертация голосового превысила 120 секунд.") from exc
            except subprocess.CalledProcessError as exc:
                raise RuntimeError("ffmpeg не смог конвертировать аудио.") from exc
            data = target.read_bytes()
        if len(data) > 25 * 1024 * 1024:
            raise RuntimeError("Голосовое больше лимита 25 МБ.")
        log.info("voice ffmpeg elapsed=%.2fs wav_bytes=%s", time.monotonic() - started, len(data))
        return data

    def transcribe(self, audio: bytes, suffix: str = ".oga", duration: int | None = None) -> str:
        started = time.monotonic()
        wav = self.convert_to_wav(audio, suffix)
        timeout = self._timeout(duration)
        max_attempts = 1 + max(STT_RETRIES, STT_RATE_LIMIT_ATTEMPTS)
        last_error: BaseException | None = None
        for attempt in range(1, max_attempts + 1):
            stt_started = time.monotonic()
            try:
                response = requests.post(
                    self.base_url + "/audio/transcriptions",
                    headers={"Authorization": "Bearer " + self.api_key},
                    files={"file": ("voice.wav", wav, "audio/wav")},
                    data={"model": self.model, "response_format": "verbose_json"},
                    timeout=timeout,
                )
            except requests.Timeout as exc:
                last_error = exc
                log.warning(
                    "voice stt timeout elapsed=%.2fs limit=%ss attempt=%s/%s duration=%s",
                    time.monotonic() - stt_started, timeout, attempt, max_attempts, duration,
                )
                if attempt <= STT_RETRIES:
                    time.sleep(min(2 * attempt, 8))
                    continue
                raise RuntimeError("Не удалось отправить голос на распознавание.") from exc
            except requests.RequestException as exc:
                last_error = exc
                log.warning(
                    "voice stt failed elapsed=%.2fs error=%s attempt=%s/%s",
                    time.monotonic() - stt_started, type(exc).__name__, attempt, max_attempts,
                )
                if attempt <= STT_RETRIES:
                    time.sleep(min(2 * attempt, 8))
                    continue
                raise RuntimeError("Не удалось отправить голос на распознавание.") from exc
            stt_elapsed = time.monotonic() - stt_started
            if response.status_code in {429, 500, 502, 503, 504}:
                wait, retry_after = _stt_retry_wait(response, attempt)
                budget = STT_RATE_LIMIT_ATTEMPTS if response.status_code == 429 else STT_RETRIES
                log.warning(
                    "voice stt http %s elapsed=%.2fs retry_after=%s wait=%.1fs attempt=%s/%s body=%s",
                    response.status_code, stt_elapsed, retry_after, wait, attempt, max_attempts,
                    (response.text or "")[:200],
                )
                if attempt <= budget:
                    time.sleep(wait)
                    continue
                if response.status_code == 429:
                    raise RuntimeError(
                        "Распознавание сейчас перегружено у провайдера. Подожди минуту и пришли голос ещё раз."
                    )
            if response.status_code >= 400:
                log.warning(
                    "voice stt http %s elapsed=%.2fs body=%s",
                    response.status_code, stt_elapsed, (response.text or "")[:300],
                )
                raise RuntimeError("Распознавание голоса не удалось. Попробуй ещё раз или напиши текстом.")
            payload = response.json()
            text = str(payload.get("text") or "").strip()
            if not text:
                raise RuntimeError("Не разобрал голос. Скажи громче или напиши текстом.")
            log.info(
                "voice stt provider=%s model=%s lang=%s elapsed=%.2fs total=%.2fs attempt=%s/%s duration=%s chars=%s",
                self.provider, self.model, payload.get("language") or "auto",
                stt_elapsed, time.monotonic() - started, attempt, max_attempts, duration, len(text),
            )
            return text
        raise RuntimeError("Не удалось отправить голос на распознавание.") from last_error

    def _timeout(self, duration: int | None) -> int:
        if duration and duration > 0:
            return max(STT_TIMEOUT, int(duration) + 90)
        return STT_TIMEOUT


def _stt_retry_wait(response, attempt: int) -> tuple[float, str | None]:
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is not None:
        try:
            return min(max(float(raw), 5.0), 60.0), str(raw)
        except (TypeError, ValueError):
            pass
    if getattr(response, "status_code", None) == 429:
        return min(10.0 * (2 ** (attempt - 1)), 60.0), None if raw is None else str(raw)
    return min(2.0 * attempt, 8.0), None if raw is None else str(raw)
