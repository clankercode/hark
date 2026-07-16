"""P1.M5 StateFeedFollower core + presentation unify."""

from __future__ import annotations

import json
from pathlib import Path

from hark.dashboard.tailer import MultiTailer, SourceTailer
from hark.monitor_feed import compact_mode_a_event
from hark.state_feed import (
    CursorPosition,
    FeedRecord,
    SourceFollower,
    StateFeedFollower,
    format_cursor,
    parse_cursor,
    parse_cursor_positions,
    present_for_monitor,
)


def _write(path: Path, *objs: dict, mode: str = "a") -> None:
    with path.open(mode, encoding="utf-8") as fh:
        for obj in objs:
            fh.write(json.dumps(obj) + "\n")


def test_source_follower_is_dashboard_source_tailer_alias():
    assert SourceTailer is SourceFollower
    assert FeedRecord.__name__ == "FeedRecord"


def test_partial_and_rotation_via_core(tmp_path: Path):
    f = tmp_path / "watch.jsonl"
    f.write_text("")
    t = SourceFollower(f, source="watch")
    t.start_at_end()
    with f.open("a") as fh:
        fh.write('{"kind": "agent.blo')
    assert list(t.poll()) == []
    with f.open("a") as fh:
        fh.write('cked"}\n')
    recs = list(t.poll())
    assert [r.payload["kind"] for r in recs] == ["agent.blocked"]

    rotated = tmp_path / "watch.jsonl.1"
    f.rename(rotated)
    _write(f, {"kind": "ambient.prompt", "text": "hi"}, mode="w")
    recs = list(t.poll())
    assert [r.payload["kind"] for r in recs] == ["ambient.prompt"]
    assert recs[0].seq == 1


def test_composite_cursor_format_roundtrip():
    assert parse_cursor("watch:12,bound:3") == {"watch": 12, "bound": 3}
    assert format_cursor({"watch": 12, "bound": 3}) == "watch:12,bound:3"
    assert format_cursor([("a", 1), ("b", 2)]) == "a:1,b:2"


def test_proved_cursor_format_roundtrip_is_opaque_and_backward_compatible():
    position = CursorPosition(
        seq=12,
        incarnation="a" * 32,
        checkpoint="b" * 32,
        byte_offset=345,
    )
    cursor = format_cursor({"watch": position, "ambient": 3})

    assert cursor == f"watch:12@{'a' * 32}~{'b' * 32}~345,ambient:3"
    assert parse_cursor(cursor) == {"watch": 12, "ambient": 3}
    assert parse_cursor_positions(cursor)["watch"] == position


def test_state_feed_follower_multi_source(tmp_path: Path):
    _write(tmp_path / "watch.jsonl", {"kind": "agent.blocked", "n": 1})
    _write(tmp_path / "ambient.jsonl", {"kind": "ambient.prompt", "text": "x"})
    follower = StateFeedFollower(
        [
            SourceFollower(tmp_path / "watch.jsonl", source="watch"),
            SourceFollower(tmp_path / "ambient.jsonl", source="ambient"),
        ]
    )
    follower.start_from(None, default_tail=100)
    recs = list(follower.poll())
    kinds = {r.payload["kind"] for r in recs}
    assert "agent.blocked" in kinds and "ambient.prompt" in kinds
    cur = parse_cursor(follower.composite_cursor())
    assert cur["watch"] >= 1 and cur["ambient"] >= 1
    follower.close()


def test_multitailer_uses_state_feed_core(tmp_path: Path):
    _write(tmp_path / "watch.jsonl", {"kind": "agent.blocked"})
    mt = MultiTailer(tmp_path)
    mt.start_from(None, default_tail=50)
    recs = list(mt.poll())
    assert any(r.payload.get("kind") == "agent.blocked" for r in recs)
    # resume cursor works
    cursor = mt.composite_cursor()
    mt.close()
    mt2 = MultiTailer(tmp_path)
    mt2.start_from(cursor)
    assert list(mt2.poll()) == []
    _write(tmp_path / "watch.jsonl", {"kind": "agent.needs_input"})
    more = list(mt2.poll())
    assert [r.payload["kind"] for r in more] == ["agent.needs_input"]
    mt2.close()


def test_present_for_monitor_is_compact_alias():
    assert present_for_monitor is not None
    ev = {
        "schema": "hark.event.v1",
        "kind": "ambient.wake_near_miss",
        "event_id": "e1",
        "attempts": [{"text": "clunker"}],
    }
    a = present_for_monitor(ev)
    b = compact_mode_a_event(ev)
    assert a == b
    assert a["attempts"] == ["clunker"]
    assert "instructions" in a


def test_present_agent_uses_monitor_profile_once():
    ev = {
        "schema": "hark.event.v1",
        "kind": "agent.blocked",
        "event_id": "e9",
        "session_id": "s1",
        "target": {"server_instance": "s1", "pane_id": "p1", "agent": "claude"},
        "state": {"to": "blocked"},
        "question": {"text": "Ship it?", "risk": "R1"},
    }
    c = present_for_monitor(ev)
    assert c["kind"] == "agent.blocked"
    assert c.get("question") == "Ship it?" or c.get("question")
    # re-present is stable enough for orchestrators
    c2 = present_for_monitor(c)
    assert c2["kind"] == "agent.blocked"
