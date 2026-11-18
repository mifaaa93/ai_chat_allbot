from unittest.mock import Mock, patch

import requests

from config import STT_TIMEOUT
from llm.transcribe import Transcriber


def test_transcription_posts_wav_and_model():
    transcriber = Transcriber(api_key="key", base_url="https://example.test/v1", model="codex-transcribe")
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"text": "привет"}
    with patch.object(transcriber, "convert_to_wav", return_value=b"RIFF audio"):
        with patch("llm.transcribe.requests.post", return_value=response) as request:
            assert transcriber.transcribe(b"oga") == "привет"
    assert request.call_args.args[0].endswith("/audio/transcriptions")
    assert request.call_args.kwargs["data"]["model"] == "codex-transcribe"
    assert "language" not in request.call_args.kwargs["data"]


def test_empty_transcription_is_user_error():
    transcriber = Transcriber(api_key="key", base_url="https://example.test/v1")
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"text": " "}
    with patch.object(transcriber, "convert_to_wav", return_value=b"RIFF audio"):
        with patch("llm.transcribe.requests.post", return_value=response):
            try:
                transcriber.transcribe(b"oga")
            except RuntimeError as exc:
                assert "Не разобрал" in str(exc)
            else:
                raise AssertionError("expected RuntimeError")


def test_timeout_scales_with_duration():
    transcriber = Transcriber(api_key="key", base_url="https://example.test/v1")
    assert transcriber._timeout(None) == STT_TIMEOUT
    assert transcriber._timeout(113) == max(STT_TIMEOUT, 203)


def test_transcription_retries_timeout_then_succeeds():
    transcriber = Transcriber(api_key="key", base_url="https://example.test/v1")
    good = Mock()
    good.status_code = 200
    good.json.return_value = {"text": "ок"}
    with patch.object(transcriber, "convert_to_wav", return_value=b"RIFF audio"):
        with patch("llm.transcribe.requests.post", side_effect=[requests.ReadTimeout(), good]):
            with patch("llm.transcribe.time.sleep"):
                assert transcriber.transcribe(b"oga", duration=10) == "ок"


def test_transcription_retries_429_capacity_then_succeeds():
    transcriber = Transcriber(api_key="key", base_url="https://example.test/v1")
    busy = Mock()
    busy.status_code = 429
    busy.headers = {}
    busy.text = '{"error":{"code":"transcription_capacity_exceeded"}}'
    good = Mock()
    good.status_code = 200
    good.json.return_value = {"text": "привет"}
    with patch.object(transcriber, "convert_to_wav", return_value=b"RIFF audio"):
        with patch("llm.transcribe.requests.post", side_effect=[busy, good]):
            with patch("llm.transcribe.time.sleep") as slept:
                assert transcriber.transcribe(b"oga") == "привет"
    assert slept.call_args.args[0] == 10.0


def test_default_transcriber_uses_groq_when_key_set():
    with patch("llm.transcribe.GROQ_API_KEY", "gsk_test"):
        with patch("llm.transcribe.GROQ_BASE_URL", "https://api.groq.com/openai/v1"):
            with patch("llm.transcribe.GROQ_TRANSCRIBE_MODEL", "whisper-large-v3-turbo"):
                transcriber = Transcriber()
    assert transcriber.provider == "groq"
    assert transcriber.model == "whisper-large-v3-turbo"
    assert transcriber.base_url.endswith("/openai/v1")


def test_stt_retry_wait_honors_retry_after_with_floor():
    from llm.transcribe import _stt_retry_wait

    response = Mock()
    response.status_code = 429
    response.headers = {"Retry-After": "1"}
    wait, raw = _stt_retry_wait(response, 1)
    assert raw == "1"
    assert wait == 5.0
