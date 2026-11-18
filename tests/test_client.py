import json
from unittest.mock import Mock, patch

import pytest
import requests

from llm.client import ChatClient, OutFile, _retry_budget, _retry_wait, is_transient
from llm.tools import ToolResult


def test_http_503_is_transient():
    response = Mock()
    response.status_code = 503
    exc = requests.HTTPError(response=response)
    assert is_transient(exc)


def test_retry_after_429_is_not_capped_at_15s():
    response = Mock()
    response.status_code = 429
    response.headers = {"Retry-After": "30"}
    exc = requests.HTTPError(response=response)
    assert _retry_wait(exc, 1) == 30


def test_complete_retries_429_then_succeeds():
    client = ChatClient(api_key="test", base_url="https://example.test/v1")
    bad = Mock()
    bad.status_code = 429
    bad.headers = {"Retry-After": "1"}
    bad.text = "rate limited"
    bad.raise_for_status.side_effect = requests.HTTPError(response=bad)
    good = Mock()
    good.json.return_value = {"choices": [{"message": {"role": "assistant", "content": "ок"}}]}
    good.raise_for_status.return_value = None
    with patch("llm.client.requests.post", side_effect=[bad, good]):
        with patch("llm.client.time.sleep") as sleep:
            with patch("llm.client.clamp_reasoning", return_value=None):
                result = client.complete([], "привет", model="gpt-6-luna")
    assert result.text == "ок"
    sleep.assert_called_once()
    assert sleep.call_args.args[0] == 1.0


def test_complete_returns_assistant_text():
    client = ChatClient(api_key="test", base_url="https://example.test/v1")
    payload = {"choices": [{"message": {"role": "assistant", "content": "ок"}}]}
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    with patch("llm.client.requests.post", return_value=response) as post:
        with patch("llm.client.clamp_reasoning", return_value="xhigh"):
            result = client.complete([], "привет", model="gpt-6-luna", reasoning="max")
    assert result.text == "ок"
    body = post.call_args.kwargs["json"]
    assert body["model"] == "gpt-6-luna"
    assert body["reasoning_effort"] == "xhigh"


def test_complete_skips_reasoning_when_unsupported():
    client = ChatClient(api_key="test", base_url="https://example.test/v1")
    payload = {"choices": [{"message": {"role": "assistant", "content": "ок"}}]}
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    with patch("llm.client.requests.post", return_value=response) as post:
        with patch("llm.client.clamp_reasoning", return_value=None):
            client.complete([], "привет", model="composer-2.5-fast", reasoning="medium")
    assert "reasoning_effort" not in post.call_args.kwargs["json"]


def test_complete_steps_down_rejected_effort():
    client = ChatClient(api_key="test", base_url="https://example.test/v1")
    bad = Mock()
    bad.status_code = 400
    bad.text = "invalid reasoning_effort: max"
    bad.raise_for_status.side_effect = requests.HTTPError(response=bad)
    good = Mock()
    good.json.return_value = {"choices": [{"message": {"role": "assistant", "content": "ок"}}]}
    good.raise_for_status.return_value = None
    with patch("llm.client.requests.post", side_effect=[bad, good]) as post:
        with patch("llm.client.clamp_reasoning", return_value="max"):
            result = client.complete([], "привет", model="gpt-6-luna", reasoning="max")
    assert result.text == "ок"
    assert post.call_args_list[0].kwargs["json"]["reasoning_effort"] == "max"
    assert post.call_args_list[1].kwargs["json"]["reasoning_effort"] == "xhigh"


def test_timeout_retry_budget_is_one():
    with patch("llm.client.CHAT_TIMEOUT_RETRIES", 1):
        assert _retry_budget(requests.Timeout()) == 1
        assert _retry_budget(requests.ConnectionError()) == 1
    response = Mock()
    response.status_code = 503
    assert _retry_budget(requests.HTTPError(response=response)) == 2


def test_complete_retries_timeout_once_then_raises():
    client = ChatClient(api_key="test", base_url="https://example.test/v1")
    events = []

    def on_progress(event, **payload):
        events.append((event, payload))

    with patch("llm.client.CHAT_TIMEOUT_RETRIES", 1):
        with patch("llm.client.requests.post", side_effect=requests.Timeout()) as post:
            with patch("llm.client.time.sleep"):
                with patch("llm.client.clamp_reasoning", return_value=None):
                    with pytest.raises(requests.Timeout):
                        client.complete([], "привет", model="gpt-6-luna", on_progress=on_progress)
    assert post.call_count == 2
    assert any(event == "retry" and payload.get("timeout") for event, payload in events)


def test_complete_emits_tool_progress_and_keeps_file():
    client = ChatClient(api_key="test", base_url="https://example.test/v1")
    first = Mock()
    first.raise_for_status.return_value = None
    first.json.return_value = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps({"filename": "a.md", "content": "hello"}),
                    },
                }],
            },
        }],
    }
    second = Mock()
    second.raise_for_status.return_value = None
    second.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "готово"}}],
    }
    events = []

    def on_progress(event, **payload):
        events.append((event, payload))

    fake_file = ToolResult(text="ok", file=("a.md", b"hello"), source_text="hello")
    with patch("llm.client.requests.post", side_effect=[first, second]):
        with patch("llm.client.clamp_reasoning", return_value=None):
            with patch("llm.client.execute_tool", return_value=fake_file) as tool:
                result = client.complete([], "сделай файл", model="gpt-6-luna", on_progress=on_progress)
    tool.assert_called_once()
    assert result.text == "готово"
    assert len(result.files) == 1
    assert isinstance(result.files[0], OutFile)
    assert result.files[0].filename == "a.md"
    kinds = [event for event, _payload in events]
    assert kinds.count("thinking") == 2
    assert "tool" in kinds
    assert "tool_done" in kinds
    tool_event = next(payload for event, payload in events if event == "tool")
    assert tool_event["name"] == "write_file"
    done = next(payload for event, payload in events if event == "tool_done")
    assert done["file"] is result.files[0]
