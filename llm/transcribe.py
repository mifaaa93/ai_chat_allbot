"""Telegram voice to text via CheapVibeCode transcriptions."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

import requests

from config import CVC_API_KEY, CVC_BASE_URL, CVC_TRANSCRIBE_MODEL, FFMPEG_BIN, STT_TIMEOUT

log = logging.getLogger(__name__)


class Transcriber:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None):
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
        return data

    def transcribe(self, audio: bytes, suffix: str = ".oga") -> str:
        wav = self.convert_to_wav(audio, suffix)
        try:
            response = requests.post(
                self.base_url + "/audio/transcriptions",
                headers={"Authorization": "Bearer " + self.api_key},
                files={"file": ("voice.wav", wav, "audio/wav")},
                data={"model": self.model, "response_format": "json", "language": "ru"},
                timeout=STT_TIMEOUT,
            )
        except requests.Timeout as exc:
            log.warning("transcription timeout after %ss: %s", STT_TIMEOUT, type(exc).__name__)
            raise RuntimeError("Не удалось отправить голос на распознавание.") from exc
        except requests.RequestException as exc:
            log.warning("transcription request failed: %s", type(exc).__name__)
            raise RuntimeError("Не удалось отправить голос на распознавание.") from exc
        if response.status_code >= 400:
            log.warning("transcription http %s", response.status_code)
            raise RuntimeError("Распознавание голоса не удалось. Попробуй ещё раз или напиши текстом.")
        text = str(response.json().get("text") or "").strip()
        if not text:
            raise RuntimeError("Не разобрал голос. Скажи громче или напиши текстом.")
        return text
