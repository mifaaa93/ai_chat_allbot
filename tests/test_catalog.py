from pathlib import Path
from unittest.mock import patch

import models_catalog
from models_catalog import (
    ALLOWED_MODEL_IDS, REASONING, ModelInfo, classify_group, clamp_reasoning, format_context,
    format_reasoning_label, get_model, listed_only, model_button_label, reasoning_efforts_for,
    reasoning_menu, supports_reasoning, supports_vision, title_for, _from_api, _pretty_title,
)


def test_reasoning_ladder_has_high_levels():
    assert list(REASONING) == ["off", "low", "medium", "high", "xhigh", "max"]


def test_clamp_reasoning_uses_nearest_supported():
    assert clamp_reasoning("gpt-6-luna", "max") == "max"
    assert clamp_reasoning("gpt-6-luna", "off") is None
    assert clamp_reasoning("grok-4.6", "max") == "xhigh"
    assert clamp_reasoning("grok-4.5", "xhigh") == "high"
    assert clamp_reasoning("gemini-3.8-flash", "max") == "high"
    assert clamp_reasoning("claude-sonnet-4-6", "xhigh") == "max"
    assert clamp_reasoning("qwen3.8-max", "high") == "xhigh"
    assert clamp_reasoning("composer-2.5-fast", "medium") is None
    assert clamp_reasoning("missing", "high") is None
    assert format_reasoning_label("grok-4.6", "max") == "XHigh ← Max"
    assert "max" not in reasoning_menu("gemini-3.8-flash")
    assert reasoning_efforts_for("gpt-6-luna")[-1] == "max"


def test_listed_only_drops_weak_models():
    keep = ModelInfo("gpt-6-luna", "GPT 6 Luna", "gpt", 0.3, True, True, 1_050_000, 128_000, ("text", "image"))
    drop = ModelInfo("nemotron-3-ultra", "Nemotron 3 Ultra", "other", 0.001, False, True, 1_000_000, 65_536, ("text",))
    assert listed_only([keep, drop]) == [keep]
    assert "gpt-6-luna" in ALLOWED_MODEL_IDS
    assert "composer-2.5-fast" not in ALLOWED_MODEL_IDS
    assert "hy4" not in ALLOWED_MODEL_IDS
    assert "gpt-5.6-luna" not in ALLOWED_MODEL_IDS


def test_default_model_has_vision():
    assert supports_vision("gpt-6-luna")
    assert title_for("gpt-6-luna") == "GPT 6 Luna"


def test_unknown_model_allows_vision():
    assert get_model("missing") is None
    assert supports_vision("missing") is True
    assert supports_reasoning("missing") is False


def test_classify_groups():
    assert classify_group("gpt-6-luna", "OpenAI") == "gpt"
    assert classify_group("claude-sonnet-5-5", "Anthropic") == "claude"
    assert classify_group("gemini-4-carbon", "Google") == "gemini"
    assert classify_group("grok-4.6", "xAI") == "grok"
    assert classify_group("deepseek-v4.1-flash-1017", "") == "cn"
    assert classify_group("nemotron-3-ultra", "") == "other"


def test_from_api_uses_display_name():
    info = _from_api({
        "id": "gpt-6-astra",
        "display_name": "OpenAI · GPT 6 Astra",
        "company": "OpenAI",
        "multiplier": 8,
        "supports_vision": True,
        "supports_reasoning": True,
        "context_window": 1_050_000,
        "max_output_tokens": 128_000,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
    })
    assert info is not None
    assert info.title == "GPT 6 Astra"
    assert info.group == "gpt"
    assert info.vision is True
    assert info.reasoning is True
    assert info.context == 1_050_000
    assert info.max_output == 128_000
    assert model_button_label(info) == "GPT 6 Astra ×8 · 1.05M"


def test_from_api_missing_reasoning_is_false():
    info = _from_api({
        "id": "composer-2.5-fast",
        "display_name": "Composer 2.5 Fast",
        "company": "xAI",
        "supports_vision": False,
        "supports_reasoning": None,
        "max_input_tokens": 200_000,
        "input_modalities": ["text"],
        "output_modalities": ["text"],
    })
    assert info is not None
    assert info.reasoning is False
    assert info.vision is False
    assert info.context == 200_000


def test_format_context():
    assert format_context(1_050_000) == "1.05M"
    assert format_context(1_000_000) == "1M"
    assert format_context(500_000) == "500K"
    assert format_context(0) == "?"


def test_pretty_title_strips_company():
    assert _pretty_title({"display_name": "Anthropic · Claude Sonnet 5.5", "id": "x"}) == "Claude Sonnet 5.5"


def test_disk_cache_skips_api(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(models_catalog, "MODELS_CACHE_PATH", str(tmp_path / "models.json"))
    monkeypatch.setattr(models_catalog, "CACHE_TTL", 3600)
    models_catalog._models = list(models_catalog.FALLBACK)
    models_catalog._fetched_at = 0.0
    sample = [
        ModelInfo("gpt-6-luna", "GPT 6 Luna", "gpt", 0.3, True, True, 1_050_000, 128_000, ("text", "image")),
    ]
    now = 1_700_000_000.0
    models_catalog.save_disk_cache(sample, now)
    with patch.object(models_catalog, "fetch_models") as fetch:
        with patch.object(models_catalog.time, "time", return_value=now + 10):
            loaded = models_catalog.refresh_catalog()
    fetch.assert_not_called()
    assert [item.model_id for item in loaded] == ["gpt-6-luna"]
