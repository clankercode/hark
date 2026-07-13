"""Listen endpoint modes: silence/Smart Turn vs radio-style end phrases.

Control phrases MUST be product-scoped by default so ordinary technical speech
does not abort or finalize a capture. Operators may add casual phrases if they
accept the false-trigger risk.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


class EndMode(str, Enum):
    SILENCE = "silence"  # end on silence / Smart Turn
    RADIO = "radio"  # keep listening until end phrase


# Product-scoped only — no "cancel that" / "send it" / bare "over".
DEFAULT_END_PHRASES: tuple[str, ...] = (
    "okay hark send",
    "ok hark send",
    "hark send it",
    "hark send",
    "end prompt",
    "end of prompt",
    "hark over",
)

DEFAULT_CANCEL_PHRASES: tuple[str, ...] = (
    "hark cancel",
    "cancel hark",
    "abort hark send",
    "hark abort",
)


_PUNCT_TRAIL = re.compile(r"[\s\.\!\?\,\;\:…]+$", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u2019", "'").replace("`", "'")
    text = text.lower().strip()
    text = _WS.sub(" ", text)
    return text


def _strip_trail_punct(text: str) -> str:
    return _PUNCT_TRAIL.sub("", text).strip()


@dataclass(frozen=True)
class PhraseHit:
    kind: str  # "end" | "cancel"
    phrase: str
    body: str
    raw: str


def _ends_with_phrase(normalized: str, phrase: str) -> bool:
    p = normalize_for_match(phrase)
    if not p or not normalized:
        return False
    if normalized == p:
        return True
    if not normalized.endswith(p):
        return False
    before = len(normalized) - len(p)
    if before == 0:
        return True
    return normalized[before - 1].isspace()


def find_terminal_phrase(
    text: str,
    phrases: list[str] | tuple[str, ...],
    *,
    kind: str,
) -> PhraseHit | None:
    raw = text or ""
    norm = normalize_for_match(raw)
    norm = _strip_trail_punct(norm)
    if not norm:
        return None

    ordered = sorted(
        (normalize_for_match(p) for p in phrases if p and str(p).strip()),
        key=len,
        reverse=True,
    )
    seen: set[str] = set()
    for p in ordered:
        if not p or p in seen:
            continue
        seen.add(p)
        if _ends_with_phrase(norm, p):
            body_norm = norm[: len(norm) - len(p)].rstrip()
            body_norm = _strip_trail_punct(body_norm)
            return PhraseHit(kind=kind, phrase=p, body=body_norm, raw=raw)
    return None


def evaluate_radio_transcript(
    text: str,
    *,
    end_phrases: list[str] | tuple[str, ...] = DEFAULT_END_PHRASES,
    cancel_phrases: list[str] | tuple[str, ...] = DEFAULT_CANCEL_PHRASES,
) -> PhraseHit | None:
    cancel = find_terminal_phrase(text, cancel_phrases, kind="cancel")
    if cancel is not None:
        return cancel
    return find_terminal_phrase(text, end_phrases, kind="end")


def parse_end_mode(value: str | None, default: EndMode = EndMode.SILENCE) -> EndMode:
    if value is None or str(value).strip() == "":
        return default
    v = str(value).strip().lower()
    if v in ("silence", "smart_turn", "smart-turn", "vad"):
        return EndMode.SILENCE
    if v == "auto":
        return default
    if v in ("radio", "prosign", "phrase", "end_phrase", "end-phrase"):
        return EndMode.RADIO
    raise ValueError(
        f"unknown listen end_mode {value!r}; use 'silence' or 'radio'"
    )


def should_keep_listening(
    end_mode: EndMode | str,
    text: str,
    *,
    end_phrases: list[str] | tuple[str, ...] = DEFAULT_END_PHRASES,
    cancel_phrases: list[str] | tuple[str, ...] = DEFAULT_CANCEL_PHRASES,
    silence_would_end: bool = False,
) -> tuple[bool, PhraseHit | None]:
    mode = end_mode if isinstance(end_mode, EndMode) else parse_end_mode(str(end_mode))
    if mode is EndMode.SILENCE:
        if silence_would_end:
            return False, None
        return True, None

    hit = evaluate_radio_transcript(
        text, end_phrases=end_phrases, cancel_phrases=cancel_phrases
    )
    if hit is None:
        return True, None
    return False, hit
