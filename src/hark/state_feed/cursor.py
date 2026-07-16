"""Composite cursor tokens for multi-source resume (dashboard SSE compatible).

Canonical positions use ``key:seq@incarnation~checkpoint~byte_offset``.
The opaque proofs and byte offset are optional for legacy sequence-only tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping


_KEY = r"[A-Za-z][A-Za-z0-9_.-]*"
_SEQUENCE = r"[0-9]{1,19}"
_PROOF = r"[a-f0-9]{32}"
_CURSOR_PART = re.compile(
    rf"({_KEY}):({_SEQUENCE})(?:@({_PROOF})~({_PROOF})(?:~({_SEQUENCE}))?)?"
)
_MAX_INTEGER = 10**19 - 1


@dataclass(frozen=True)
class CursorPosition:
    """One source position with optional opaque resume proof and byte offset."""

    seq: int
    incarnation: str | None = None
    checkpoint: str | None = None
    byte_offset: int | None = None


def parse_cursor_positions(cursor: str | None) -> dict[str, CursorPosition]:
    """Leniently parse valid cursor parts while retaining proof metadata."""
    positions: dict[str, CursorPosition] = {}
    if not cursor:
        return positions
    for raw_part in cursor.split(","):
        match = _CURSOR_PART.fullmatch(raw_part.strip())
        if match is None:
            continue
        key, raw_seq, incarnation, checkpoint, raw_offset = match.groups()
        positions[key] = CursorPosition(
            seq=int(raw_seq),
            incarnation=incarnation,
            checkpoint=checkpoint,
            byte_offset=int(raw_offset) if raw_offset is not None else None,
        )
    return positions


def parse_cursor(cursor: str | None) -> dict[str, int]:
    """Return sequence positions for compatibility with legacy callers."""
    return {
        key: position.seq for key, position in parse_cursor_positions(cursor).items()
    }


def format_cursor(
    positions: Mapping[str, int | CursorPosition]
    | Iterable[tuple[str, int | CursorPosition]],
) -> str:
    """Build a composite cursor; preserves iteration order of *positions*."""
    items = positions.items() if isinstance(positions, Mapping) else positions
    return ",".join(_format_part(key, position) for key, position in items)


def _format_part(key: str, position: int | CursorPosition) -> str:
    if not isinstance(position, CursorPosition):
        position = CursorPosition(seq=int(position))
    if not re.fullmatch(_KEY, key):
        raise ValueError("invalid cursor key")
    values = (position.seq, position.byte_offset)
    if any(value is not None and not 0 <= value <= _MAX_INTEGER for value in values):
        raise ValueError("cursor integer outside supported range")
    has_proof = position.incarnation is not None or position.checkpoint is not None
    if has_proof and not (position.incarnation and position.checkpoint):
        raise ValueError("cursor proof must include incarnation and checkpoint")
    suffix = ""
    if position.incarnation and position.checkpoint:
        if not re.fullmatch(_PROOF, position.incarnation) or not re.fullmatch(
            _PROOF, position.checkpoint
        ):
            raise ValueError("invalid cursor proof")
        suffix = f"@{position.incarnation}~{position.checkpoint}"
        if position.byte_offset is not None:
            suffix += f"~{position.byte_offset}"
    elif position.byte_offset is not None:
        raise ValueError("cursor byte offset requires proof")
    return f"{key}:{position.seq}{suffix}"


def canonicalize_cursor(cursor: str) -> str:
    """Strictly validate external cursor text before reflecting it into SSE."""
    if not cursor:
        raise ValueError("cursor must not be empty")
    positions: list[tuple[str, CursorPosition]] = []
    seen: set[str] = set()
    for part in cursor.split(","):
        match = _CURSOR_PART.fullmatch(part)
        if match is None:
            raise ValueError("invalid cursor grammar")
        key, raw_seq, incarnation, checkpoint, raw_offset = match.groups()
        if key in seen:
            raise ValueError("duplicate cursor key")
        seen.add(key)
        positions.append(
            (
                key,
                CursorPosition(
                    seq=int(raw_seq),
                    incarnation=incarnation,
                    checkpoint=checkpoint,
                    byte_offset=(int(raw_offset) if raw_offset is not None else None),
                ),
            )
        )
    return format_cursor(positions)
