"""CheapVibeCode image generation."""

from __future__ import annotations

import base64
import logging

import requests

from config import CVC_API_KEY, CVC_BASE_URL, CVC_IMAGE_MODEL, IMAGE_TIMEOUT

log = logging.getLogger(__name__)


def generate_image(prompt: str, quality: str = "low", model: str | None = None) -> bytes:
    payload = {
        "model": model or CVC_IMAGE_MODEL,
        "prompt": prompt,
        "size": "auto",
        "quality": quality if quality in {"low", "medium", "high"} else "low",
        "n": 1,
        "response_format": "b64_json",
    }
    response = requests.post(
        CVC_BASE_URL.rstrip("/") + "/images/generations",
        headers={"Authorization": "Bearer " + CVC_API_KEY},
        json=payload,
        timeout=IMAGE_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json().get("data") or []
    if not data or not data[0].get("b64_json"):
        raise RuntimeError("API не вернул изображение.")
    return base64.b64decode(data[0]["b64_json"], validate=True)
