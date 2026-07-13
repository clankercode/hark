"""Activation-phrase detection for ambient (non-answer) listening.

Policy:
  - Ambient path MUST NOT open cloud STT until an activation phrase fires.
  - Short local snippets (default ~2.5 s) are scanned by a small local model
    or a mock/test backend. Full dictation after wake still uses cloud STT.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

from hark.listen_end import normalize_for_match

DEFAULT_ACTIVATION_PHRASES: tuple[str, ...] = (
    "hey hark",
    "hey herald",
    "okay hark",
    "ok hark",
)

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[\.\!\?\,\;\:…]+")


@dataclass(frozen=True)
class WakeHit:
    phrase: str
    remainder: str  # text after activation, if any
    raw: str
    confidence: float = 1.0
    backend: str = "text"


def match_activation(
    text: str,
    phrases: list[str] | tuple[str, ...] = DEFAULT_ACTIVATION_PHRASES,
) -> WakeHit | None:
    """Match activation at start of text (or whole short snippet)."""
    raw = text or ""
    norm = normalize_for_match(raw)
    norm = _PUNCT.sub(" ", norm)
    norm = _WS.sub(" ", norm).strip()
    if not norm:
        return None

    ordered = sorted(
        (normalize_for_match(p) for p in phrases if p and str(p).strip()),
        key=len,
        reverse=True,
    )
    for p in ordered:
        if not p:
            continue
        if norm == p:
            return WakeHit(phrase=p, remainder="", raw=raw, backend="text")
        if norm.startswith(p + " "):
            rem = norm[len(p) :].strip()
            return WakeHit(phrase=p, remainder=rem, raw=raw, backend="text")
    return None


class WakeBackend(Protocol):
    name: str

    def score_snippet(self, pcm16_le: bytes, sample_rate: int = 16000) -> WakeHit | None:
        """Return WakeHit if activation detected in this short PCM snippet."""
        ...


class TextProbeBackend:
    """Test/dev backend: treat UTF-8 payload as already-transcribed text.

    Production uses Vosk/tiny-local; this allows unit tests without models.
    """

    name = "text_probe"

    def __init__(self, phrases: list[str] | tuple[str, ...] | None = None) -> None:
        self.phrases = list(phrases or DEFAULT_ACTIVATION_PHRASES)

    def score_snippet(self, pcm16_le: bytes, sample_rate: int = 16000) -> WakeHit | None:
        # Convention: if buffer starts with magic b"TXT:" rest is utf-8 text
        if pcm16_le.startswith(b"TXT:"):
            text = pcm16_le[4:].decode("utf-8", errors="replace")
            hit = match_activation(text, self.phrases)
            if hit:
                return WakeHit(
                    phrase=hit.phrase,
                    remainder=hit.remainder,
                    raw=hit.raw,
                    backend=self.name,
                )
        return None


class VoskWakeBackend:
    """Optional tiny local ASR on short snippets (vosk model path required)."""

    name = "vosk"

    def __init__(
        self,
        model_path: str,
        phrases: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.model_path = model_path
        self.phrases = list(phrases or DEFAULT_ACTIVATION_PHRASES)
        self._model = None
        self._rec = None

    def _ensure(self, sample_rate: int) -> None:
        if self._model is not None:
            return
        try:
            from vosk import KaldiRecognizer, Model  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "vosk not installed; pip install vosk or uv sync --extra wake"
            ) from exc
        self._model = Model(self.model_path)
        self._Rec = KaldiRecognizer
        self._sample_rate = sample_rate

    def score_snippet(self, pcm16_le: bytes, sample_rate: int = 16000) -> WakeHit | None:
        self._ensure(sample_rate)
        rec = self._Rec(self._model, sample_rate)
        rec.AcceptWaveform(pcm16_le)
        import json

        try:
            data = json.loads(rec.FinalResult())
        except Exception:
            return None
        text = str(data.get("text") or "").strip()
        if not text:
            return None
        hit = match_activation(text, self.phrases)
        if not hit:
            return None
        return WakeHit(
            phrase=hit.phrase,
            remainder=hit.remainder,
            raw=text,
            confidence=0.8,
            backend=self.name,
        )


def build_wake_backend(
    engine: str,
    *,
    phrases: list[str] | tuple[str, ...],
    model_path: str | None = None,
) -> WakeBackend:
    engine = (engine or "vosk").lower()
    if engine in ("off", "none", "disabled"):
        return TextProbeBackend(phrases)  # inert unless TXT: probe
    if engine in ("text_probe", "mock", "test"):
        return TextProbeBackend(phrases)
    if engine == "vosk":
        if not model_path:
            raise RuntimeError(
                "ambient.engine=vosk requires ambient.model_path "
                "(download a small vosk model)"
            )
        return VoskWakeBackend(model_path, phrases)
    raise ValueError(f"unknown ambient wake engine: {engine!r}")
