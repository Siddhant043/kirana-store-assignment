"""Unit tests for hosted Whisper transcription (mocked httpx)."""

import httpx
import pytest

from src.domain.voice import WhisperTranscriber


def _success_transport(text: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/audio/transcriptions")
        return httpx.Response(200, json={"text": text})

    return httpx.MockTransport(handler)


def _error_transport(status_code: int, body: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=body)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_transcribe_returns_text_on_success() -> None:
    transport = _success_transport("2kg sugar, 4 Maggi, UPI")
    async with httpx.AsyncClient(transport=transport) as client:
        transcriber = WhisperTranscriber(
            api_key="test-key",
            api_base_url="https://api.openai.com/v1",
            model="whisper-1",
            http_client=client,
        )
        result = await transcriber.transcribe(b"fake-ogg-bytes", filename="voice.ogg")

    assert result.status == "ok"
    assert result.text == "2kg sugar, 4 Maggi, UPI"
    assert result.reason is None


@pytest.mark.asyncio
async def test_transcribe_returns_failed_on_http_error() -> None:
    transport = _error_transport(500, "internal error")
    async with httpx.AsyncClient(transport=transport) as client:
        transcriber = WhisperTranscriber(
            api_key="test-key",
            api_base_url="https://api.openai.com/v1",
            model="whisper-1",
            http_client=client,
        )
        result = await transcriber.transcribe(b"fake-ogg-bytes")

    assert result.status == "failed"
    assert result.text is None
    assert result.reason is not None
    assert "500" in result.reason or "error" in result.reason.lower()


@pytest.mark.asyncio
async def test_transcribe_returns_failed_on_empty_transcript() -> None:
    transport = _success_transport("   ")
    async with httpx.AsyncClient(transport=transport) as client:
        transcriber = WhisperTranscriber(
            api_key="test-key",
            api_base_url="https://api.openai.com/v1",
            model="whisper-1",
            http_client=client,
        )
        result = await transcriber.transcribe(b"fake-ogg-bytes")

    assert result.status == "failed"
    assert result.text is None
    assert result.reason is not None
