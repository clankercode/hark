"""Spoken confirmation / cancel lexicon for ask --confirm."""

from __future__ import annotations

from hark.listen_end import normalize_for_match

AFFIRM = frozenset(
    {
        "yes",
        "yeah",
        "yep",
        "yup",
        "correct",
        "confirm",
        "confirmed",
        "send",
        "do it",
        "go ahead",
        "affirmative",
        "ok",
        "okay",
        "sure",
        "right",
    }
)

NEGATE = frozenset(
    {
        "no",
        "nope",
        "cancel",
        "abort",
        "stop",
        "don't",
        "do not",
        "never mind",
        "nevermind",
        "negative",
        "wrong",
        "scratch",
    }
)


def classify_confirm_reply(text: str) -> str:
    """Return 'yes' | 'no' | 'unclear'."""
    t = normalize_for_match(text)
    if not t:
        return "unclear"
    if t in AFFIRM:
        return "yes"
    if t in NEGATE:
        return "no"
    for a in sorted(AFFIRM, key=len, reverse=True):
        if t == a or t.startswith(a + " ") or t.endswith(" " + a):
            if not any(n in t for n in ("no ", "not ", "don't", "cancel")):
                return "yes"
    for n in sorted(NEGATE, key=len, reverse=True):
        if t == n or t.startswith(n + " ") or f" {n}" in f" {t}":
            return "no"
    return "unclear"
