"""Tests for hark.logview formatting helpers (no TTY required)."""

from __future__ import annotations

import json
from pathlib import Path

from hark.logview import (
    classify_record,
    format_extras,
    format_hep_record,
    format_log_line,
    format_system_record,
    format_timestamp,
    resolve_sources,
    tail_pretty,
    use_color,
)


def test_use_color_no_color_flag():
    assert use_color(no_color=True) is False


def test_use_color_env_no_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert use_color(no_color=False) is False


def test_use_color_force(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert use_color(no_color=False) is True
    assert use_color(no_color=True) is False  # flag wins


def test_format_timestamp_unix():
    # 2026-ish fixed epoch with ms
    s = format_timestamp(1_700_000_000.123456, with_date=True, with_ms=True, local=False)
    assert s.startswith("2023-11-14")
    assert ".123" in s


def test_format_timestamp_iso():
    s = format_timestamp("2026-07-13T11:18:05.041Z", with_date=False, with_ms=True, local=False)
    assert s == "11:18:05.041"


def test_format_timestamp_missing():
    assert format_timestamp(None) == "--:--:--"


def test_format_system_record_no_color():
    rec = {
        "ts": 1_700_000_000.0,
        "level": "info",
        "component": "tts",
        "event": "tts.ok",
        "message": "tts",
        "data": {"provider": "xai", "voice": "eve", "chars": 11},
    }
    line = format_system_record(rec, color=False)
    assert "\033[" not in line
    assert "INFO" in line
    assert "tts" in line
    assert "tts.ok" in line
    assert "provider=xai" in line
    assert "voice=eve" in line


def test_format_system_record_color_and_error():
    rec = {
        "ts": 1_700_000_000.0,
        "level": "error",
        "component": "ambient",
        "event": "ambient.error",
        "message": "boom",
        "data": {},
    }
    line = format_system_record(rec, color=True)
    assert "\033[" in line
    assert "ERROR" in line
    assert "boom" in line
    assert line.endswith("\033[0m") or "boom" in line


def test_format_system_skips_duplicate_message():
    rec = {
        "ts": 1_700_000_000.0,
        "level": "info",
        "component": "audio",
        "event": "mic.muted",
        "message": "mic.muted",
        "data": {},
    }
    line = format_system_record(rec, color=False)
    # message equal to event should not be repeated as body
    assert line.count("mic.muted") == 1


def test_format_hep_record():
    rec = {
        "schema": "hark.event.v1",
        "kind": "agent.blocked",
        "event_id": "19f5b4dc27a4eacb1c13d843a61",
        "observed_at": "2026-07-13T11:47:30.554Z",
        "session_id": "default",
        "pane_id": "w1:p6",
        "risk": "R2",
        "question": "Do you want to proceed?",
    }
    line = format_hep_record(rec, color=False, source="watch")
    assert "HEP" in line
    assert "agent.blocked" in line
    assert "watch" in line
    assert "pane_id=w1:p6" in line
    assert "risk=R2" in line
    assert "Do you want to proceed?" in line


def test_format_log_line_system_and_raw():
    sys_line = json.dumps(
        {
            "ts": 1_700_000_000.0,
            "level": "warn",
            "component": "watch",
            "event": "watch.error",
            "message": "socket down",
            "data": {"error": "broken pipe"},
        }
    )
    out = format_log_line(sys_line, color=False, source="system")
    assert out is not None
    assert "WARN" in out
    assert "socket down" in out

    raw = format_log_line("LOG (VoskAPI:ReadDataFiles())", color=False, source="ambient")
    assert raw is not None
    assert "RAW" in raw
    assert "VoskAPI" in raw

    assert format_log_line("   ", color=False) is None


def test_classify_record():
    assert (
        classify_record(
            {"ts": 1.0, "level": "info", "component": "hark", "event": "x"}
        )
        == "system"
    )
    assert (
        classify_record(
            {"schema": "hark.event.v1", "kind": "watch.armed", "event_id": "a"}
        )
        == "hep"
    )
    assert classify_record({"foo": 1}) == "other"


def test_format_extras_truncates_long_text():
    long = "x" * 200
    s = format_extras({"text": long, "provider": "xai"})
    assert "provider=xai" in s
    assert "…" in s
    assert len(s) < 120


def test_resolve_sources_default_and_all(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("HARK_SYSTEM_LOG", raising=False)
    default = resolve_sources()
    assert [n for n, _ in default] == ["system"]
    assert default[0][1] == tmp_path / "hark" / "system.jsonl"

    all_s = resolve_sources(include_all=True)
    assert [n for n, _ in all_s] == ["system", "ambient", "watch"]
    assert all_s[1][1] == tmp_path / "hark" / "ambient.jsonl"


def test_tail_pretty_merged(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    state = tmp_path / "hark"
    state.mkdir()
    sys_path = state / "system.jsonl"
    amb_path = state / "ambient.jsonl"
    rows = [
        {
            "ts": 100.0,
            "level": "info",
            "component": "audio",
            "event": "mic.muted",
            "message": "mic.muted",
            "data": {},
        },
        {
            "ts": 300.0,
            "level": "info",
            "component": "tts",
            "event": "tts.ok",
            "message": "tts",
            "data": {"provider": "xai"},
        },
    ]
    sys_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    amb_path.write_text(
        json.dumps(
            {
                "schema": "hark.event.v1",
                "kind": "ambient.prompt",
                "event_id": "abc",
                "observed_at": "1970-01-01T00:00:02Z",  # ts ~2
                "text": "hello there",
                "phrase": "hey hark",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    sources = [("system", sys_path), ("ambient", amb_path)]
    lines = tail_pretty(sources, 10, color=False)
    assert len(lines) == 3
    # order by timestamp: system@100, ambient@2? wait ambient observed_at is epoch 2
    # system 100, ambient ~2, system 300 → ambient, mic, tts
    joined = "\n".join(lines)
    assert "ambient.prompt" in joined
    assert "mic.muted" in joined
    assert "tts.ok" in joined
    # chronological: ambient (~2) then mic (100) then tts (300)
    assert joined.index("ambient.prompt") < joined.index("mic.muted")
    assert joined.index("mic.muted") < joined.index("tts.ok")


def test_cli_watch_logs_help():
    from hark.cli import build_parser

    p = build_parser()
    # ensure subcommand exists
    ns = p.parse_args(["watch-logs", "--no-follow", "-n", "0", "--no-color"])
    assert ns.cmd == "watch-logs"
    assert ns.follow is False
    assert ns.no_color is True
    assert ns.lines == 0


def test_cmd_watch_logs_snapshot(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("HARK_SYSTEM_LOG", raising=False)
    state = tmp_path / "hark"
    state.mkdir()
    rec = {
        "ts": 1_700_000_000.5,
        "level": "info",
        "component": "stt",
        "event": "stt.ok",
        "message": "stt",
        "data": {"provider": "xai", "chars": 10},
    }
    (state / "system.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")

    from hark.cli import build_parser, dispatch

    args = build_parser().parse_args(
        ["watch-logs", "--no-follow", "--no-color", "-n", "5"]
    )
    rc = dispatch(args, cfg=None)
    assert rc == 0
    out = capsys.readouterr().out
    assert "stt.ok" in out
    assert "provider=xai" in out
    assert "\033[" not in out
