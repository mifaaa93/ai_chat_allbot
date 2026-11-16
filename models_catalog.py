"""CheapVibeCode chat models for the settings menu."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

from config import CATALOG_TTL_SECONDS, CVC_API_KEY, CVC_BASE_URL, MODELS_CACHE_PATH, ROOT

log = logging.getLogger(__name__)

CACHE_TTL = CATALOG_TTL_SECONDS
CACHE_VERSION = 2


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    title: str
    group: str
    multiplier: float
    vision: bool
    reasoning: bool
    context: int
    max_output: int
    inputs: tuple[str, ...]


ALLOWED_MODEL_IDS = frozenset({
    "gpt-6-luna",
    "gpt-6.1-terra",
    "gpt-6-sol",
    "gpt-6.1-sol",
    "gpt-6-astra",
    "claude-haiku-5-5",
    "claude-sonnet-5-5",
    "claude-opus-5-5",
    "claude-fable-5-2",
    "gemini-3.8-flash",
    "gemini-4-argon",
    "gemini-4-carbon",
    "grok-4.6",
    "grok-4.7",
    "deepseek-v4.1-flash-1017",
    "deepseek-v4-pro-0813",
    "qwen3.8-flash",
    "qwen3.8-max",
    "qwen-4-max-preview",
    "kimi-k3",
    "kimi-k3.1-pro",
    "glm-5.3-flash",
    "glm-5.3",
    "minimax-m3.1-flash",
})

FALLBACK: tuple[ModelInfo, ...] = (
    ModelInfo("gpt-6-luna", "GPT 6 Luna", "gpt", 0.3, True, True, 1_050_000, 128_000, ("text", "image")),
    ModelInfo("gpt-6.1-sol", "GPT 6.1 Sol", "gpt", 2.0, True, True, 1_050_000, 128_000, ("text", "image")),
    ModelInfo("claude-sonnet-5-5", "Claude Sonnet 5.5", "claude", 2.0, True, True, 1_000_000, 128_000, ("text", "image")),
    ModelInfo("gemini-3.8-flash", "Gemini 3.8 Flash", "gemini", 2.0, True, True, 1_048_576, 65_536, ("text", "image")),
    ModelInfo("grok-4.6", "Grok 4.6", "grok", 2.0, True, True, 500_000, 0, ("text", "image")),
    ModelInfo("deepseek-v4.1-flash-1017", "DeepSeek V4.1 Flash", "cn", 0.16, True, True, 1_048_576, 393_216, ("text", "image")),
)

GROUP_ORDER: tuple[tuple[str, str], ...] = (
    ("gpt", "GPT"),
    ("claude", "Claude"),
    ("gemini", "Gemini"),
    ("grok", "Grok"),
    ("cn", "Китайские"),
    ("other", "Другие"),
)
GROUPS = tuple(key for key, _ in GROUP_ORDER)
GROUP_TITLES = dict(GROUP_ORDER)

STYLES = {
    "normal": "Обычный",
    "brief": "Краткий",
    "code": "Код",
}
REASONING = {
    "off": "Выкл",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "XHigh",
    "max": "Max",
}
REASONING_ORDER = ("off", "low", "medium", "high", "xhigh", "max")
_REASONING_ALIASES = {
    "none": "off",
    "minimal": "low",
    "extra": "xhigh",
    "extra-high": "xhigh",
    "extra_high": "xhigh",
}
IMAGE_QUALITY = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
}

_lock = threading.Lock()
_models: list[ModelInfo] = list(FALLBACK)
_fetched_at = 0.0


def cache_path() -> Path:
    path = Path(MODELS_CACHE_PATH)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _info_from_dict(raw: dict) -> ModelInfo:
    return ModelInfo(
        model_id=str(raw["model_id"]),
        title=str(raw.get("title") or raw["model_id"]),
        group=str(raw.get("group") or "other"),
        multiplier=float(raw.get("multiplier") or 1),
        vision=bool(raw.get("vision")),
        reasoning=bool(raw.get("reasoning")),
        context=int(raw.get("context") or 0),
        max_output=int(raw.get("max_output") or 0),
        inputs=tuple(raw.get("inputs") or ("text",)),
    )


def load_disk_cache() -> tuple[list[ModelInfo], float] | None:
    path = cache_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("version") or 0) != CACHE_VERSION:
            return None
        fetched_at = float(payload.get("fetched_at") or 0)
        models = listed_only([_info_from_dict(item) for item in payload.get("models") or []])
    except (OSError, ValueError, TypeError, KeyError):
        log.warning("models cache unreadable: %s", path)
        return None
    if not models:
        return None
    return models, fetched_at


def save_disk_cache(models: list[ModelInfo], fetched_at: float) -> None:
    path = cache_path()
    payload = {
        "version": CACHE_VERSION,
        "fetched_at": fetched_at,
        "models": [asdict(item) for item in models],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _cache_fresh(fetched_at: float, now: float | None = None) -> bool:
    stamp = now if now is not None else time.time()
    return fetched_at > 0 and stamp - fetched_at < CACHE_TTL

_CN_MARKERS = (
    "qwen", "kimi", "glm", "deepseek", "minimax", "mimo", "hy4", "moonshot", "zhipu",
)


def classify_group(model_id: str, company: str = "") -> str:
    blob = f"{company} {model_id}".lower()
    if "openai" in blob or model_id.startswith("gpt-"):
        return "gpt"
    if "anthropic" in blob or model_id.startswith("claude-"):
        return "claude"
    if "google" in blob or model_id.startswith("gemini-"):
        return "gemini"
    if "xai" in blob or model_id.startswith("grok-") or model_id.startswith("composer-"):
        return "grok"
    if any(marker in blob for marker in _CN_MARKERS):
        return "cn"
    return "other"


def _pretty_title(raw: dict) -> str:
    name = str(raw.get("display_name") or raw.get("id") or "model")
    if " · " in name:
        name = name.split(" · ", 1)[1]
    return name.strip()[:40]


def _from_api(raw: dict) -> ModelInfo | None:
    model_id = str(raw.get("id") or "").strip()
    if not model_id:
        return None
    outputs = tuple(raw.get("output_modalities") or ("text",))
    if "text" not in outputs:
        return None
    inputs = tuple(raw.get("input_modalities") or ("text",))
    vision = bool(raw.get("supports_vision")) or "image" in inputs
    reasoning = bool(raw.get("supports_reasoning"))
    context = _first_int(raw, "context_window", "contextWindow", "context_length", "max_context_tokens", "max_input_tokens")
    max_output = _first_int(raw, "max_output_tokens", "max_tokens")
    try:
        multiplier = float(raw.get("multiplier") or raw.get("base_multiplier") or 1)
    except (TypeError, ValueError):
        multiplier = 1.0
    return ModelInfo(
        model_id=model_id,
        title=_pretty_title(raw),
        group=classify_group(model_id, str(raw.get("company") or "")),
        multiplier=multiplier,
        vision=vision,
        reasoning=reasoning,
        context=context,
        max_output=max_output,
        inputs=inputs,
    )


def _first_int(raw: dict, *keys: str) -> int:
    for key in keys:
        value = raw.get(key)
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def fetch_models() -> list[ModelInfo]:
    response = requests.get(
        CVC_BASE_URL.rstrip("/") + "/models",
        headers={"Authorization": "Bearer " + CVC_API_KEY},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("data") or payload.get("models") or []
    models = []
    seen = set()
    for raw in items:
        info = _from_api(raw)
        if info is None or info.model_id in seen or info.model_id not in ALLOWED_MODEL_IDS:
            continue
        seen.add(info.model_id)
        models.append(info)
    models.sort(key=lambda item: (GROUPS.index(item.group) if item.group in GROUPS else 99, item.multiplier, item.title))
    if not models:
        raise RuntimeError("empty catalog")
    return models


def listed_only(models: list[ModelInfo]) -> list[ModelInfo]:
    return [item for item in models if item.model_id in ALLOWED_MODEL_IDS]


def refresh_catalog(force: bool = False) -> list[ModelInfo]:
    global _models, _fetched_at
    now = time.time()
    with _lock:
        if not force and _models and _cache_fresh(_fetched_at, now):
            return list(_models)
    if not force:
        disk = load_disk_cache()
        if disk is not None:
            models, fetched_at = disk
            if _cache_fresh(fetched_at, now):
                with _lock:
                    _models = models
                    _fetched_at = fetched_at
                log.info("catalog from cache %s models age=%.0fs", len(models), now - fetched_at)
                return list(models)
    try:
        models = fetch_models()
        fetched_at = time.time()
        save_disk_cache(models, fetched_at)
    except Exception:
        log.warning("catalog refresh failed, keeping %s models", len(_models), exc_info=True)
        with _lock:
            return list(_models)
    with _lock:
        _models = models
        _fetched_at = fetched_at
    log.info("catalog loaded %s chat models, cached %ss", len(models), CACHE_TTL)
    return list(models)


def all_models() -> list[ModelInfo]:
    with _lock:
        return list(_models)


def get_model(model_id: str) -> ModelInfo | None:
    for item in all_models():
        if item.model_id == model_id:
            return item
    return None


def supports_vision(model_id: str) -> bool:
    info = get_model(model_id)
    if info is None:
        return True
    return info.vision


def supports_reasoning(model_id: str) -> bool:
    info = get_model(model_id)
    if info is None:
        return False
    return info.reasoning


def reasoning_efforts_for(model_id: str) -> tuple[str, ...]:
    """API effort values this model accepts. Empty means do not send reasoning_effort."""
    info = get_model(model_id)
    if info is not None and not info.reasoning:
        return ()
    mid = (model_id or "").lower()
    if mid.startswith("gpt-"):
        return ("low", "medium", "high", "xhigh", "max")
    if mid.startswith("claude-"):
        if "-4-6" in mid:
            return ("low", "medium", "high", "max")
        return ("low", "medium", "high", "xhigh", "max")
    if mid.startswith("grok-"):
        if mid.startswith("grok-4.5"):
            return ("low", "medium", "high")
        return ("low", "medium", "high", "xhigh")
    if mid.startswith("gemini-"):
        return ("low", "medium", "high")
    if mid.startswith("qwen"):
        return ("low", "medium", "xhigh")
    if info is None:
        return ()
    return ("low", "medium", "high")


def reasoning_menu(model_id: str) -> dict[str, str]:
    options = {"off": REASONING["off"]}
    for level in reasoning_efforts_for(model_id):
        options[level] = REASONING.get(level, level)
    return options


def clamp_reasoning(model_id: str, requested: str | None) -> str | None:
    """Effort to send, or None to omit the field."""
    allowed = reasoning_efforts_for(model_id)
    if not allowed:
        return None
    want = _normalize_reasoning(requested)
    if want == "off":
        return None
    if want in allowed:
        return want
    order = REASONING_ORDER
    if want not in order:
        want = "medium"
    idx = order.index(want)
    best: str | None = None
    best_dist = 99
    for level in allowed:
        if level not in order:
            continue
        dist = abs(order.index(level) - idx)
        if best is None or dist < best_dist or (dist == best_dist and order.index(level) > order.index(best)):
            best = level
            best_dist = dist
    return best


def lower_reasoning(level: str | None) -> str | None:
    want = _normalize_reasoning(level)
    if want == "off":
        return None
    idx = REASONING_ORDER.index(want) if want in REASONING_ORDER else -1
    if idx <= 1:
        return None
    return REASONING_ORDER[idx - 1]


def format_reasoning_label(model_id: str, requested: str | None) -> str:
    if not supports_reasoning(model_id):
        return "нет у этой модели"
    want = _normalize_reasoning(requested)
    effective = clamp_reasoning(model_id, want)
    if effective is None:
        return REASONING["off"]
    label = REASONING.get(effective, effective)
    if want not in ("off", effective) and want in REASONING:
        return f"{label} ← {REASONING[want]}"
    return label


def _normalize_reasoning(value: str | None) -> str:
    text = (value or "off").strip().lower()
    return _REASONING_ALIASES.get(text, text or "off")


def models_in_group(group: str) -> list[ModelInfo]:
    return [item for item in all_models() if item.group == group]


def group_title(group: str) -> str:
    return GROUP_TITLES.get(group, group)


def format_multiplier(value: float) -> str:
    text = f"{value:g}".replace(".", ",")
    return f"×{text}"


def format_context(tokens: int) -> str:
    if tokens >= 1_000_000:
        text = f"{tokens / 1_000_000:.2f}".rstrip("0").rstrip(".")
        return f"{text}M"
    if tokens >= 1000:
        return f"{round(tokens / 1000)}K"
    if tokens > 0:
        return str(tokens)
    return "?"


def model_button_label(item: ModelInfo) -> str:
    label = f"{item.title} {format_multiplier(item.multiplier)}"
    if item.context:
        label += f" · {format_context(item.context)}"
    return label[:64]


def capabilities_line(item: ModelInfo) -> str:
    bits = []
    if item.vision:
        bits.append("зрение")
    if item.reasoning:
        bits.append("reasoning")
    return ", ".join(bits) if bits else "только текст"


def title_for(model_id: str) -> str:
    info = get_model(model_id)
    return info.title if info else model_id
