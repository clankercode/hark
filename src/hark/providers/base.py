"""Provider interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, code: int = 4) -> None:
        super().__init__(message)
        self.code = code


class ProviderUnsupported(ProviderError):
    pass


@dataclass
class Transcript:
    text: str
    provider: str
    duration_ms: int = 0
    confidence: float | None = None


@dataclass
class SynthResult:
    audio: bytes  # wav or provider format
    provider: str
    content_type: str = "audio/wav"
    voice: str | None = None


class SttProvider(Protocol):
    name: str

    def transcribe(self, wav_bytes: bytes, *, language: str | None = None) -> Transcript:
        ...


class TtsProvider(Protocol):
    name: str

    def synthesize(self, text: str, *, voice: str | None = None) -> SynthResult:
        ...
