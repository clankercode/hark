"""Multi-session poll watch → HEP events on stdout."""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Callable, TextIO

from hark.config import HarkConfig, SessionConfig
from hark.events import (
    make_agent_status_event,
    make_watch_armed,
    make_watch_error,
    make_watch_heartbeat,
    monitor_profile,
)
from hark.fingerprint import question_fingerprint
from hark.herdr.client import AgentInfo, HerdrClient, HerdrError


EmitFn = Callable[[dict[str, Any]], None]


def _default_emit(event: dict[str, Any], *, for_monitor: bool, out: TextIO) -> None:
    payload = monitor_profile(event) if for_monitor else event
    out.write(json.dumps(payload, separators=(",", ":")) + "\n")
    out.flush()


class EdgeTracker:
    """Track last status per (session, pane) and emit edges; dedupe by fingerprint."""

    def __init__(self) -> None:
        self._status: dict[tuple[str, str], str] = {}
        self._dedupe: set[tuple[str, str, str, str]] = set()  # session,pane,status,fp

    def process(
        self,
        agents: list[AgentInfo],
        *,
        interest: set[str],
        question_for: Callable[[AgentInfo], str | None] | None = None,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        seen_panes: set[tuple[str, str]] = set()

        for agent in agents:
            key = (agent.session_id, agent.pane_id)
            seen_panes.add(key)
            prev = self._status.get(key)
            cur = agent.status
            if prev == cur:
                continue
            self._status[key] = cur

            # Cold start: reconcile already-blocked only (SPEC §6), not every done.
            if prev is None:
                if cur != "blocked" or "blocked" not in interest:
                    continue
            elif cur not in interest and prev not in interest:
                continue

            q_text = None
            if cur == "blocked" and question_for:
                q_text = question_for(agent)
            fp = question_fingerprint(q_text or "", None) if q_text else ""
            dkey = (agent.session_id, agent.pane_id, cur, fp)
            if cur == "blocked" and fp and dkey in self._dedupe:
                continue
            if cur == "blocked" and fp:
                self._dedupe.add(dkey)

            if cur in interest or (prev is not None and prev in interest):
                events.append(
                    make_agent_status_event(
                        agent,
                        from_status=prev,
                        to_status=cur,
                        question_text=q_text,
                    )
                )
        return events


def run_watch(
    cfg: HarkConfig,
    *,
    session_ids: list[str] | None = None,
    statuses: list[str] | None = None,
    for_monitor: bool = False,
    transport: str | None = None,
    once: bool = False,
    out: TextIO | None = None,
    read_questions: bool = False,
) -> int:
    """Poll Herdr sessions and emit HEP JSONL. Returns exit code."""
    out = out or sys.stdout
    transport = transport or cfg.watch.transport
    # v1: poll path always available; socket subscribe later
    if transport == "socket":
        # Fall through to poll with a note — full subscribe in later slice
        transport = "poll"

    interest = set(statuses or cfg.watch.statuses)
    sessions = cfg.sessions
    if session_ids:
        want = set(session_ids)
        sessions = [s for s in cfg.sessions if s.id in want]
        if not sessions:
            for sid in session_ids:
                sessions.append(SessionConfig(id=sid))

    clients = [HerdrClient(s) for s in sessions]
    tracker = EdgeTracker()
    poll_s = max(0.2, cfg.watch.poll_ms / 1000.0)
    heartbeat_s = max(5.0, cfg.watch.heartbeat_s)
    last_heartbeat = time.monotonic()

    def emit(event: dict[str, Any]) -> None:
        _default_emit(event, for_monitor=for_monitor, out=out)

    emit(
        make_watch_armed(
            [s.id for s in sessions],
            transport="poll",
            statuses=sorted(interest),
        )
    )

    def question_for(agent: AgentInfo) -> str | None:
        if not read_questions:
            return None
        try:
            client = next(c for c in clients if c.session.id == agent.session_id)
            text = client.read_pane(agent.pane_id, lines=40)
            from hark.events import extract_question_excerpt

            return extract_question_excerpt(text) or None
        except (HerdrError, StopIteration):
            return None

    try:
        while True:
            for client in clients:
                try:
                    agents = client.list_agents()
                except HerdrError as exc:
                    emit(make_watch_error(client.session.id, str(exc)))
                    continue
                for event in tracker.process(
                    agents, interest=interest, question_for=question_for
                ):
                    emit(event)

            if once:
                return 0

            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_s:
                emit(make_watch_heartbeat([s.id for s in sessions]))
                last_heartbeat = now
            time.sleep(poll_s)
    except KeyboardInterrupt:
        return 0
