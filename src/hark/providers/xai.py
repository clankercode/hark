"""xAI STT/TTS via Grok OAuth or XAI_API_KEY."""

from __future__ import annotations

import json
from typing import Any

import httpx

from hark.providers.auth import resolve_xai_token
from hark.providers.base import ProviderError, SynthResult, Transcript

STT_URL = "https://api.x.ai/v1/stt"
TTS_URL = "https://api.x.ai/v1/tts"
DEFAULT_VOICE = "eve"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token() -> str:
    tok = resolve_xai_token()
    if not tok:
        raise ProviderError(
            "xAI auth missing — run `grok login` or set XAI_API_KEY"
        )
    return tok


class XaiStt:
    name = "xai"

    def __init__(self, timeout: float = 120.0) -> None:
        self.timeout = timeout

    def transcribe(self, wav_bytes: bytes, *, language: str | None = None) -> Transcript:
        token = _token()
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data: dict[str, Any] = {}
        if language:
            data["language"] = language
        with httpx.Client(timeout=self.timeout) as client:
            # Try multipart file first; fall back to JSON body shapes if needed
            r = client.post(
                STT_URL,
                headers=_headers(token),
                files=files,
                data=data or None,
            )
            if r.status_code == 404:
                # alternate path seen in some docs
                r = client.post(
                    "https://api.x.ai/v1/audio/transcriptions",
                    headers=_headers(token),
                    files=files,
                    data=data or None,
                )
            if r.status_code == 401:
                raise ProviderError(
                    "xAI STT 401 — run `grok login` or set XAI_API_KEY"
                )
            if r.status_code >= 400:
                raise ProviderError(f"xAI STT HTTP {r.status_code}: {r.text[:300]}")
            payload = r.json()
        text = (
            payload.get("text")
            or payload.get("transcript")
            or payload.get("result", {}).get("text")
            or ""
        )
        if isinstance(payload.get("words"), list) and not text:
            text = " ".join(
                str(w.get("word") or w.get("text") or "") for w in payload["words"]
            )
        return Transcript(text=str(text).strip(), provider=self.name)


class XaiTts:
    name = "xai"

    def __init__(self, timeout: float = 120.0, voice: str = DEFAULT_VOICE) -> None:
        self.timeout = timeout
        self.voice = voice

    def synthesize(self, text: str, *, voice: str | None = None) -> SynthResult:
        token = _token()
        # Docs: text + language required; voice accepted as "voice" (voice_id also works alone)
        body = {
            "text": text,
            "voice": voice or self.voice,
            "language": "en",
        }
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(
                TTS_URL,
                headers={**_headers(token), "Content-Type": "application/json"},
                json=body,
            )
            if r.status_code == 401:
                raise ProviderError(
                    "xAI TTS 401 — run `grok login` or set XAI_API_KEY"
                )
            if r.status_code >= 400:
                raise ProviderError(f"xAI TTS HTTP {r.status_code}: {r.text[:300]}")
            ctype = r.headers.get("content-type", "audio/mpeg")
            if "json" in ctype:
                payload = r.json()
                import base64

                b64 = payload.get("audio") or payload.get("data")
                if not b64:
                    raise ProviderError(
                        f"xAI TTS JSON missing audio: {list(payload)[:8]}"
                    )
                audio = base64.b64decode(b64)
                return SynthResult(
                    audio=audio,
                    provider=self.name,
                    content_type="audio/wav",
                    voice=voice or self.voice,
                )
            return SynthResult(
                audio=r.content,
                provider=self.name,
                content_type=ctype,
                voice=voice or self.voice,
            )
