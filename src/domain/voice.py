"""Hosted Whisper transcription (OpenAI-compatible HTTP API)."""

from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

TranscriptionStatus = Literal["ok", "failed"]


@dataclass(frozen=True)
class TranscriptionResult:
    status: TranscriptionStatus
    text: str | None
    reason: str | None


class VoiceTranscriber(Protocol):
    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        filename: str = "voice.ogg",
    ) -> TranscriptionResult: ...


class WhisperTranscriber:
    """Calls an OpenAI-compatible /audio/transcriptions endpoint via httpx."""

    def __init__(
        self,
        *,
        api_key: str,
        api_base_url: str = "https://api.openai.com/v1",
        model: str = "whisper-1",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_base_url = api_base_url.rstrip("/")
        self._model = model
        self._http_client = http_client

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        filename: str = "voice.ogg",
    ) -> TranscriptionResult:
        client = self._http_client
        close_client = False
        if client is None:
            client = httpx.AsyncClient()
            close_client = True
        try:
            return await self._transcribe_with_client(
                client,
                audio_bytes,
                filename=filename,
            )
        finally:
            if close_client:
                await client.aclose()

    async def _transcribe_with_client(
        self,
        client: httpx.AsyncClient,
        audio_bytes: bytes,
        *,
        filename: str,
    ) -> TranscriptionResult:
        url = f"{self._api_base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        files = {"file": (filename, audio_bytes, "application/octet-stream")}
        data = {"model": self._model}
        try:
            response = await client.post(
                url,
                headers=headers,
                files=files,
                data=data,
                timeout=60.0,
            )
        except httpx.HTTPError as error:
            return TranscriptionResult(
                status="failed",
                text=None,
                reason=f"transcription request failed: {error}",
            )

        if response.status_code >= 400:
            return TranscriptionResult(
                status="failed",
                text=None,
                reason=(
                    f"transcription API error {response.status_code}: "
                    f"{response.text[:200]}"
                ),
            )

        try:
            payload = response.json()
        except ValueError:
            return TranscriptionResult(
                status="failed",
                text=None,
                reason="transcription API returned non-JSON body",
            )

        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            return TranscriptionResult(
                status="failed",
                text=None,
                reason="transcription was empty or unclear",
            )

        return TranscriptionResult(
            status="ok",
            text=text.strip(),
            reason=None,
        )
