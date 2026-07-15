"""Composite cursor tokens for multi-source resume (dashboard SSE compatible).

Format: ``key:seq,key:seq,…`` e.g. ``watch:184,ambient:42,bound:12``.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping


_CURSOR_PART = re.compile(r"([A-Za-z][A-Za-z0-9_.-]*):([0-9]+)")


def parse_cursor(cursor: str | None) -> dict[str, int]:
    """``"watch:12,system:9"`` → ``{"watch": 12, "system": 9}`` (lenient)."""
    out: dict[str, int] = {}
    if not cursor:
        return out
    for part in cursor.split(","):
        key, _, num = part.strip().partition(":")
        if key and num.isdigit():
            out[key] = int(num)
    return out


def format_cursor(
    positions: Mapping[str, int] | Iterable[tuple[str, int]],
) -> str:
    """Build a composite cursor; preserves iteration order of *positions*."""
    if isinstance(positions, Mapping):
        items = positions.items()
    else:
        items = positions
    return ",".join(f"{key}:{int(seq)}" for key, seq in items)


def canonicalize_cursor(cursor: str) -> str:
    """Validate an external cursor token and return its canonical form.

    Unlike :func:`parse_cursor`, this is deliberately strict because cursor
    text is reflected into SSE ``id:`` fields.  Reject separators, whitespace,
    duplicate keys, and control-character injection rather than ignoring them.
    """
    if not cursor:
        raise ValueError("cursor must not be empty")
    positions: list[tuple[str, int]] = []
    seen: set[str] = set()
    for part in cursor.split(","):
        match = _CURSOR_PART.fullmatch(part)
        if match is None:
            raise ValueError("invalid cursor grammar")
        key, raw_seq = match.groups()
        if key in seen:
            raise ValueError("duplicate cursor key")
        seen.add(key)
        positions.append((key, int(raw_seq)))
    return format_cursor(positions)
