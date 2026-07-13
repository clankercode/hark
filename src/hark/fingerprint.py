"""Question fingerprinting for bound delivery."""

from __future__ import annotations

import hashlib
import re
import unicodedata


_WS = re.compile(r"\s+")


def normalize_question_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.strip().lower()
    text = _WS.sub(" ", text)
    return text


def question_fingerprint(text: str, choices: list[str] | None = None) -> str:
    """Stable fingerprint over normalized question text + choices.

    Uses blake2b (stdlib) with a blake3-compatible label prefix for HEP.
    """
    parts = [normalize_question_text(text)]
    if choices:
        parts.append("|")
        parts.extend(normalize_question_text(c) for c in choices)
    payload = "\n".join(parts).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=16).hexdigest()
    return f"blake2b:{digest}"
