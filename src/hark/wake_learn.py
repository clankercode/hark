"""Persistent learned wake aliases (hot-reloadable, no process restart).

State file: ``~/.local/state/hark/wake_learned.json``

- **names mode:** alternate name tokens (vosk mishears) map → canonical name
- **phrases mode:** alternate full phrases that should wake

Ambient reloads this file by mtime on each wake cycle and after each learn
write so new aliases apply without SIGHUP or restart.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hark.paths import state_dir

_LOCK = threading.Lock()
_LEARNED_NAME = "wake_learned.json"

# Learned name-token constraints (seed aliases in wake.py are separate).
NAME_ALIAS_MIN_LEN = 3
NAME_ALIAS_MAX_LEN = 12

# Common English stop/function words that must never become wake name aliases.
# TTS bleed (“This is Eve…”) otherwise maps is→iris via char similarity.
# Closed-class words only — keep open-class content words learnable as mishears.
_NAME_ALIAS_STOPWORDS = frozenset(
    {
        # articles / determiners
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "some",
        "any",
        "all",
        "each",
        "every",
        "both",
        "few",
        "many",
        "much",
        "more",
        "most",
        "other",
        "another",
        "such",
        "no",
        "nor",
        # pronouns
        "i",
        "me",
        "my",
        "mine",
        "myself",
        "we",
        "us",
        "our",
        "ours",
        "ourselves",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "he",
        "him",
        "his",
        "himself",
        "she",
        "her",
        "hers",
        "herself",
        "it",
        "its",
        "itself",
        "they",
        "them",
        "their",
        "theirs",
        "themselves",
        "who",
        "whom",
        "whose",
        "which",
        "what",
        # auxiliaries / copula / common verbs
        "am",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "having",
        "do",
        "does",
        "did",
        "doing",
        "done",
        "will",
        "would",
        "shall",
        "should",
        "can",
        "could",
        "may",
        "might",
        "must",
        "ought",
        "need",
        "dare",
        # prepositions / particles
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "as",
        "into",
        "onto",
        "upon",
        "about",
        "above",
        "below",
        "under",
        "over",
        "between",
        "among",
        "through",
        "during",
        "before",
        "after",
        "against",
        "without",
        "within",
        "along",
        "across",
        "behind",
        "beyond",
        "near",
        "off",
        "out",
        "up",
        "down",
        "around",
        # conjunctions
        "and",
        "or",
        "but",
        "if",
        "than",
        "because",
        "while",
        "although",
        "though",
        "unless",
        "until",
        "since",
        "whether",
        "either",
        "neither",
        # common adverbs / discourse
        "not",
        "yes",
        "yeah",
        "yep",
        "nope",
        "so",
        "very",
        "too",
        "just",
        "only",
        "also",
        "even",
        "still",
        "already",
        "always",
        "never",
        "often",
        "really",
        "quite",
        "rather",
        "here",
        "there",
        "where",
        "when",
        "why",
        "how",
        "then",
        "now",
        "again",
        "once",
        "twice",
        "well",
        "like",
        "else",
        "away",
        "back",
        "yet",
        "ever",
        # greating-ish tokens (not wake names themselves)
        "hey",
        "hello",
        "hi",
        "yo",
        "sup",
        "okay",
        "ok",
        "please",
        "thanks",
        "thank",
        "sorry",
        # TTS sample bleed fragments
        "english",
        "sample",
        "voice",
        "calm",
        "eve",
        "leo",
    }
)


def is_learnable_name_alias(alias: str) -> bool:
    """True if *alias* may be auto-learned or loaded as a name→canonical map key.

    Rejects empty/short/long tokens and common English stop/function words so
    TTS bleed like “this is Eve” cannot teach ``is`` → iris. Seed aliases
    (``_SEED_NAME_ALIASES`` in wake.py) are applied separately and are not
    gated by this helper.
    """
    ak = (alias or "").strip().lower()
    if not ak:
        return False
    if len(ak) < NAME_ALIAS_MIN_LEN or len(ak) > NAME_ALIAS_MAX_LEN:
        return False
    # Single token only (no spaces / punctuation)
    if not ak.isalpha():
        return False
    if ak in _NAME_ALIAS_STOPWORDS:
        return False
    return True


def learned_path() -> Path:
    override = os.environ.get("HARK_WAKE_LEARNED")
    if override:
        return Path(override)
    return state_dir() / _LEARNED_NAME


@dataclass
class LearnedWake:
    """In-memory learned wake expansions."""

    # alias token (lower) → canonical name (lower)
    name_aliases: dict[str, str] = field(default_factory=dict)
    # full alternate phrases (as stored, lower-ish normalized)
    phrase_aliases: list[str] = field(default_factory=list)
    path: Path | None = None
    mtime_ns: int = 0

    def copy(self) -> LearnedWake:
        return LearnedWake(
            name_aliases=dict(self.name_aliases),
            phrase_aliases=list(self.phrase_aliases),
            path=self.path,
            mtime_ns=self.mtime_ns,
        )


def _empty(path: Path | None = None) -> LearnedWake:
    return LearnedWake(path=path or learned_path())


def load_learned(path: Path | None = None) -> LearnedWake:
    p = path or learned_path()
    if not p.is_file():
        return _empty(p)
    try:
        st = p.stat()
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return _empty(p)
    if not isinstance(raw, dict):
        return _empty(p)
    names: dict[str, str] = {}
    for k, v in (raw.get("name_aliases") or {}).items():
        ak = str(k).strip().lower()
        av = str(v).strip().lower()
        # Ignore bad/stale aliases (e.g. is→iris from TTS bleed) at load.
        if ak and av and is_learnable_name_alias(ak):
            names[ak] = av
    phrases: list[str] = []
    seen: set[str] = set()
    for item in raw.get("phrase_aliases") or []:
        s = str(item).strip().lower()
        if s and s not in seen:
            seen.add(s)
            phrases.append(s)
    return LearnedWake(
        name_aliases=names,
        phrase_aliases=phrases,
        path=p,
        mtime_ns=getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
    )


def load_learned_if_changed(
    current: LearnedWake | None,
    path: Path | None = None,
) -> LearnedWake:
    """Reload from disk only when mtime changes (or first load)."""
    p = path or (current.path if current and current.path else learned_path())
    if not p.is_file():
        empty = _empty(p)
        if current is None:
            return empty
        if current.name_aliases or current.phrase_aliases:
            return empty
        return current
    try:
        st = p.stat()
        mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    except OSError:
        return current or _empty(p)
    if current is not None and current.mtime_ns == mtime_ns and current.path == p:
        return current
    return load_learned(p)


def save_learned(learned: LearnedWake, path: Path | None = None) -> LearnedWake:
    p = path or learned.path or learned_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "name_aliases": dict(sorted(learned.name_aliases.items())),
        "phrase_aliases": list(learned.phrase_aliases),
    }
    with _LOCK:
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(p)
        st = p.stat()
    learned.path = p
    learned.mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    return learned


def learn_name_alias(
    alias: str,
    canonical: str,
    *,
    learned: LearnedWake | None = None,
    path: Path | None = None,
) -> tuple[LearnedWake, bool]:
    """Persist a name alias. Returns (state, changed).

    Refuses short/common stop-word aliases (see :func:`is_learnable_name_alias`).
    """
    ak = (alias or "").strip().lower()
    ck = (canonical or "").strip().lower()
    if not ak or not ck or ak == ck or not is_learnable_name_alias(ak):
        return learned or load_learned(path), False
    state = (learned.copy() if learned else None) or load_learned(path)
    if state.name_aliases.get(ak) == ck:
        return state, False
    state.name_aliases[ak] = ck
    save_learned(state, path or state.path)
    return state, True


def learn_phrase_alias(
    phrase: str,
    *,
    learned: LearnedWake | None = None,
    path: Path | None = None,
) -> tuple[LearnedWake, bool]:
    """Persist a full-phrase alternate. Returns (state, changed)."""
    s = (phrase or "").strip().lower()
    if not s:
        return learned or load_learned(path), False
    state = (learned.copy() if learned else None) or load_learned(path)
    if s in {p.lower() for p in state.phrase_aliases}:
        return state, False
    state.phrase_aliases.append(s)
    save_learned(state, path or state.path)
    return state, True


def learned_event(
    *,
    kind: str,
    value: str,
    canonical: str | None = None,
    mode: str,
    total_name_aliases: int,
    total_phrase_aliases: int,
) -> dict[str, Any]:
    from hark.events import new_event_id, utc_now_iso

    return {
        "schema": "hark.event.v1",
        "kind": "ambient.wake_learned",
        "event_id": new_event_id(),
        "observed_at": utc_now_iso(),
        "priority": 30,
        "disposition": "info",
        "learn_kind": kind,  # "name" | "phrase"
        "value": value,
        "canonical": canonical,
        "wake_mode": mode,
        "total_name_aliases": total_name_aliases,
        "total_phrase_aliases": total_phrase_aliases,
        "instructions": (
            "Learned a new wake alternate from a failed activation attempt. "
            "Applies immediately (no restart). Persisted under "
            f"{learned_path()}. To make permanent in config: names mode → "
            "[ambient] names / extra_names; phrases mode → "
            "trigger_phrases / extra_trigger_phrases. See docs/CUSTOM_WAKE.md."
        ),
    }
