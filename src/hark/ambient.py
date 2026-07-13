"""Ambient listen: local wake snippets, then cloud STT for the prompt body."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from hark.audio.capture import MicLease, record_seconds
from hark.config import HarkConfig
from hark.speech import run_listen
from hark.wake import WakeHit, build_wake_backend


@dataclass
class AmbientResult:
    activated: bool
    phrase: str | None
    text: str | None
    wake_backend: str | None = None
    listen: dict[str, Any] | None = None


def run_ambient(
    cfg: HarkConfig,
    *,
    once: bool = True,
    timeout_s: float | None = None,
) -> AmbientResult:
    """Scan short local snippets until activation, then cloud-listen for prompt.

    Does NOT use cloud STT during the wake scan (except test text_probe).
    """
    amb = cfg.ambient
    if not amb.enabled and not once:
        return AmbientResult(activated=False, phrase=None, text=None)

    phrases = amb.activation_phrases
    backend = build_wake_backend(
        amb.engine,
        phrases=phrases,
        model_path=amb.model_path,
    )
    deadline = time.monotonic() + (timeout_s or amb.timeout_s or 300.0)
    snippet = max(1.0, amb.snippet_s)

    with MicLease("ambient"):
        while time.monotonic() < deadline:
            try:
                pcm = record_seconds(snippet, sample_rate=16000)
            except Exception as exc:
                return AmbientResult(
                    activated=False,
                    phrase=None,
                    text=None,
                    wake_backend=backend.name,
                    listen={"error": str(exc)},
                )
            hit: WakeHit | None = backend.score_snippet(pcm, 16000)
            if hit is None:
                # optional: if engine is text_probe only, never fires on real audio
                if once and amb.engine in ("text_probe", "mock", "test"):
                    # no activation in this test-only path
                    pass
                if once and time.monotonic() + snippet >= deadline:
                    break
                continue

            # Activation — release lease before cloud listen (nested lease)
            remainder = hit.remainder
            break
        else:
            return AmbientResult(
                activated=False, phrase=None, text=None, wake_backend=backend.name
            )

    # outside lease: full listen for prompt body
    if hit is None:
        return AmbientResult(
            activated=False, phrase=None, text=None, wake_backend=backend.name
        )

    if remainder and len(remainder.split()) >= 3:
        # prompt already in same utterance after wake phrase
        text = remainder
        # still honor radio end if remainder includes end phrase later — treat as body
        return AmbientResult(
            activated=True,
            phrase=hit.phrase,
            text=text,
            wake_backend=hit.backend,
            listen={"provider": "inline_after_wake", "duration_ms": 0},
        )

    listened = run_listen(cfg, end_mode=cfg.listen.end_mode)
    return AmbientResult(
        activated=True,
        phrase=hit.phrase,
        text=listened.text,
        wake_backend=hit.backend,
        listen={
            "provider": listened.provider,
            "duration_ms": listened.duration_ms,
            "end_phrase": listened.end_phrase,
            "cancelled": listened.cancelled,
        },
    )
