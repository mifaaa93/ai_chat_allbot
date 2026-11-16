from unittest.mock import Mock, patch

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
