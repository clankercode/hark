"""Parse session/pane target strings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    session_id: str
    pane_id: str

    def __str__(self) -> str:
        return f"{self.session_id}/{self.pane_id}"


def parse_target(value: str, default_session: str | None = None) -> Target:
    """Parse `session/pane` or bare `pane` with --session / default."""
    value = (value or "").strip()
    if not value:
        raise ValueError("empty target")
    if "/" in value:
        session_id, pane_id = value.split("/", 1)
        session_id = session_id.strip()
        pane_id = pane_id.strip()
        if not session_id or not pane_id:
            raise ValueError(f"invalid target: {value!r}")
        return Target(session_id=session_id, pane_id=pane_id)
    if not default_session:
        raise ValueError(
            f"target {value!r} needs session (use session/pane or --session)"
        )
    return Target(session_id=default_session, pane_id=value)
