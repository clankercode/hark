"""Human-readable colorful live log viewer for ``hark watch-logs``.

Formats ``system.jsonl`` (and optionally Mode A ``ambient.jsonl`` /
``watch.jsonl``) with ANSI colors, timestamps, and compact data highlights.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence, TextIO

from hark.paths import state_dir
from hark.syslog import system_log_path, tail_lines

# ANSI
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

_LEVEL_STYLE: dict[str, str] = {
    "debug": "\033[2m",  # dim
    "info": "\033[36m",  # cyan
    "warn": "\033[33m",  # yellow
    "warning": "\033[33m",
    "error": "\033[31;1m",  # bold red
    "hep": "\033[35m",  # magenta
    "raw": "\033[90m",  # bright black
}

_COMPONENT_STYLE: dict[str, str] = {
    "ambient": "\033[35m",  # magenta
    "audio": "\033[34m",  # blue
    "tts": "\033[32m",  # green
    "stt": "\033[92m",  # bright green
    "watch": "\033[94m",  # bright blue
    "hark": "\033[37m",  # white
    "daemon": "\033[90m",
    "delivery": "\033[96m",
    "listen": "\033[93m",
    "mic": "\033[34m",
    "test": "\033[90m",
    "system": "\033[37m",
}

# Compact data keys shown as key=value highlights (order preserved).
_HIGHLIGHT_KEYS: tuple[str, ...] = (
    "provider",
    "voice",
    "phrase",
    "raw",
    "last_text",
    "text",
    "rms",
    "audio_ms",
    "latency_ms",
    "chars",
    "words",
    "cue",
    "source",
    "pane_id",
    "session_id",
    "agent",
    "risk",
    "status_to",
    "engine",
    "confidence",
    "backend",
    "event_id",
    "stream_id",
    "ok",
    "error",
)

DEFAULT_SOURCES: tuple[str, ...] = ("system",)
ALL_SOURCES: tuple[str, ...] = ("system", "ambient", "watch")


def source_path(name: str) -> Path:
    """Resolve a named log source under the state dir (or system override)."""
    if name == "system":
        return system_log_path()
    return state_dir() / f"{name}.jsonl"


def resolve_sources(
    names: Sequence[str] | None = None,
    *,
    include_all: bool = False,
) -> list[tuple[str, Path]]:
    """Return ``(label, path)`` pairs for the requested sources."""
    if include_all:
        names = ALL_SOURCES
    elif not names:
        names = DEFAULT_SOURCES
    out: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for n in names:
        key = n.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((key, source_path(key)))
    return out


def use_color(
    *,
    stream: TextIO | None = None,
    no_color: bool = False,
    force: bool | None = None,
) -> bool:
    """Whether to emit ANSI color codes.

    Honors ``--no-color``, ``NO_COLOR``, ``FORCE_COLOR``, and TTY detection.
    """
    if no_color:
        return False
    if force is False:
        return False
    if force is True:
        return True
    if os.environ.get("NO_COLOR", "").strip():
        return False
    if os.environ.get("FORCE_COLOR", "").strip() not in ("", "0"):
        return True
    stream = stream if stream is not None else sys.stdout
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def _paint(text: str, style: str, *, color: bool) -> str:
    if not color or not style:
        return text
    return f"{style}{text}{_RESET}"


def format_timestamp(
    ts: Any,
    *,
    with_date: bool = False,
    with_ms: bool = True,
    local: bool = True,
) -> str:
    """Format a unix timestamp or ISO string for human display."""
    dt: datetime | None = None
    if isinstance(ts, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return str(ts)
    elif isinstance(ts, str) and ts.strip():
        s = ts.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return ts
    if dt is None:
        return "--:--:--"
    if local:
        dt = dt.astimezone()
    if with_date:
        base = dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        base = dt.strftime("%H:%M:%S")
    if with_ms:
        return f"{base}.{dt.microsecond // 1000:03d}"
    return base


def format_extras(data: dict[str, Any] | None, *, max_items: int = 8) -> str:
    """Compact ``key=value`` highlights from a data dict (or HEP event fields)."""
    if not data:
        return ""
    bits: list[str] = []
    for k in _HIGHLIGHT_KEYS:
        if k not in data:
            continue
        v = data[k]
        if v is None or v == "":
            continue
        if isinstance(v, str) and len(v) > 80:
            v = v[:77] + "…"
        elif isinstance(v, float):
            v = f"{v:.3g}"
        bits.append(f"{k}={v}")
        if len(bits) >= max_items:
            break
    return "  ".join(bits)


def format_system_record(rec: dict[str, Any], *, color: bool = True) -> str:
    """Pretty one-line format for a ``system.jsonl`` LogEvent record."""
    level = str(rec.get("level") or "info").lower()
    comp = str(rec.get("component") or "?")
    ev = str(rec.get("event") or "?")
    msg = str(rec.get("message") or "")
    if msg == ev:
        msg = ""
    data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
    extras = format_extras(data)  # type: ignore[arg-type]
    tss = format_timestamp(rec.get("ts"))

    lvl = _paint(f"{level.upper():5}", _LEVEL_STYLE.get(level, ""), color=color)
    cmp_s = _paint(f"{comp:8}", _COMPONENT_STYLE.get(comp, "\033[37m"), color=color)
    ev_s = _paint(f"{ev:22}", _BOLD, color=color)
    ts_s = _paint(tss, _DIM, color=color)
    msg_s = msg
    if extras:
        extras_s = _paint(extras, _DIM, color=color)
        tail = f"{msg_s}  {extras_s}".strip() if msg_s else extras_s
    else:
        tail = msg_s
    parts = [ts_s, lvl, cmp_s, ev_s]
    if tail:
        parts.append(tail)
    return "  ".join(parts)


def format_hep_record(
    rec: dict[str, Any],
    *,
    color: bool = True,
    source: str = "watch",
) -> str:
    """Pretty one-line format for a HEP / Mode A event (watch/ambient JSONL)."""
    kind = str(rec.get("kind") or rec.get("event") or "?")
    level = "error" if "error" in kind or rec.get("error") else "hep"
    tss = format_timestamp(rec.get("observed_at") or rec.get("ts"))
    # Prefer message-like fields
    msg = ""
    for key in ("question", "text", "error", "instructions", "message"):
        v = rec.get(key)
        if isinstance(v, str) and v.strip():
            msg = " ".join(v.split())
            if len(msg) > 100:
                msg = msg[:97] + "…"
            break
    # extras from top-level event fields
    extras = format_extras(
        {
            k: rec.get(k)
            for k in _HIGHLIGHT_KEYS
            if k in rec and k not in ("text", "question", "error", "event_id")
        }
    )
    eid = rec.get("event_id")
    if eid and "event_id" not in (extras or ""):
        short = str(eid)
        if len(short) > 12:
            short = short[:10] + "…"
        extras = (f"id={short}  " + extras).strip()

    lvl = _paint(f"{'HEP' if level == 'hep' else 'ERROR':5}", _LEVEL_STYLE.get(level, ""), color=color)
    cmp_s = _paint(f"{source:8}", _COMPONENT_STYLE.get(source, "\033[37m"), color=color)
    ev_s = _paint(f"{kind:22}", _BOLD, color=color)
    ts_s = _paint(tss, _DIM, color=color)
    if extras:
        extras_s = _paint(extras, _DIM, color=color)
        tail = f"{msg}  {extras_s}".strip() if msg else extras_s
    else:
        tail = msg
    parts = [ts_s, lvl, cmp_s, ev_s]
    if tail:
        parts.append(tail)
    return "  ".join(parts)


def format_raw_line(
    line: str,
    *,
    color: bool = True,
    source: str = "raw",
    ts: float | None = None,
) -> str:
    """Format a non-JSON worker log line."""
    tss = format_timestamp(ts if ts is not None else time.time())
    text = line.rstrip("\n")
    if len(text) > 200:
        text = text[:197] + "…"
    ts_s = _paint(tss, _DIM, color=color)
    lvl = _paint(f"{'RAW':5}", _LEVEL_STYLE["raw"], color=color)
    cmp_s = _paint(f"{source:8}", _COMPONENT_STYLE.get(source, "\033[90m"), color=color)
    body = _paint(text, _DIM, color=color)
    return f"{ts_s}  {lvl}  {cmp_s}  {body}"


def classify_record(obj: dict[str, Any]) -> str:
    """Return ``system``, ``hep``, or ``other`` for a parsed JSON object."""
    if "component" in obj and ("event" in obj or "level" in obj) and "ts" in obj:
        return "system"
    if obj.get("schema") == "hark.event.v1" or (
        "kind" in obj and ("event_id" in obj or "observed_at" in obj)
    ):
        return "hep"
    return "other"


def format_log_line(
    raw: str,
    *,
    color: bool = True,
    source: str = "system",
) -> str | None:
    """Format one log line (JSON or plain). Empty / whitespace → None."""
    line = raw.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return format_raw_line(line, color=color, source=source)

    if not isinstance(obj, dict):
        return format_raw_line(line, color=color, source=source)

    kind = classify_record(obj)
    if kind == "system":
        return format_system_record(obj, color=color)
    if kind == "hep":
        return format_hep_record(obj, color=color, source=source)
    # unknown JSON — still show something useful
    tss = format_timestamp(obj.get("ts") or obj.get("observed_at") or time.time())
    preview = json.dumps(obj, separators=(",", ":"), default=str)
    if len(preview) > 160:
        preview = preview[:157] + "…"
    label = f"{'JSON':5}"
    src = f"{source:8}"
    return (
        f"{_paint(tss, _DIM, color=color)}  "
        f"{_paint(label, _LEVEL_STYLE['raw'], color=color)}  "
        f"{_paint(src, _COMPONENT_STYLE.get(source, ''), color=color)}  "
        f"{preview}"
    )


def _record_sort_key(rec: dict[str, Any]) -> float:
    ts = rec.get("ts")
    if isinstance(ts, (int, float)):
        return float(ts)
    obs = rec.get("observed_at")
    if isinstance(obs, str):
        try:
            s = obs.strip().replace("Z", "+00:00")
            return datetime.fromisoformat(s).timestamp()
        except ValueError:
            pass
    return 0.0


def tail_pretty(
    sources: Sequence[tuple[str, Path]],
    n: int = 40,
    *,
    color: bool = True,
) -> list[str]:
    """Last *n* records across sources, merged by timestamp, pretty-formatted."""
    if n <= 0:
        return []
    collected: list[tuple[float, int, str, dict[str, Any] | str]] = []
    order = 0
    for label, path in sources:
        if not path.is_file():
            continue
        # For system.jsonl use structured tail; for others read more lines raw
        if label == "system":
            for rec in tail_lines(n, path):
                collected.append((_record_sort_key(rec), order, label, rec))
                order += 1
        else:
            for rec in _tail_mixed(path, n):
                if isinstance(rec, dict):
                    collected.append((_record_sort_key(rec), order, label, rec))
                else:
                    collected.append((0.0, order, label, rec))
                order += 1
    collected.sort(key=lambda t: (t[0], t[1]))
    # keep last n overall
    kept = collected[-n:]
    lines: list[str] = []
    for _, _, label, item in kept:
        if isinstance(item, dict):
            kind = classify_record(item)
            if kind == "system":
                lines.append(format_system_record(item, color=color))
            elif kind == "hep":
                lines.append(format_hep_record(item, color=color, source=label))
            else:
                preview = json.dumps(item, separators=(",", ":"), default=str)
                formatted = format_log_line(preview, color=color, source=label)
                if formatted:
                    lines.append(formatted)
        else:
            formatted = format_raw_line(str(item), color=color, source=label)
            lines.append(formatted)
    return lines


def _tail_mixed(path: Path, n: int) -> list[dict[str, Any] | str]:
    """Tail last n non-empty lines; parse JSON when possible."""
    if not path.is_file() or n <= 0:
        return []
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        block = 8192
        data = b""
        while size > 0 and data.count(b"\n") <= n:
            step = min(block, size)
            size -= step
            fh.seek(size)
            data = fh.read(step) + data
        raw_lines = data.splitlines()[-n:]
    out: list[dict[str, Any] | str] = []
    for raw in raw_lines:
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                out.append(obj)
                continue
        except json.JSONDecodeError:
            pass
        out.append(text)
    return out


def follow_pretty(
    sources: Sequence[tuple[str, Path]],
    *,
    color: bool = True,
    poll_s: float = 0.25,
    out: TextIO | None = None,
    stop_after: float | None = None,
) -> int:
    """Follow sources forever (or until *stop_after* seconds). Returns 0.

    Prints new lines as they appear. Handles log rotation (size shrink).
    """
    out = out if out is not None else sys.stdout
    positions: dict[str, int] = {}
    for label, path in sources:
        key = str(path)
        if path.is_file():
            positions[key] = path.stat().st_size
        else:
            positions[key] = 0

    deadline = time.monotonic() + stop_after if stop_after is not None else None
    try:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                return 0
            for label, path in sources:
                key = str(path)
                if not path.is_file():
                    positions[key] = 0
                    continue
                size = path.stat().st_size
                pos = positions.get(key, 0)
                if size < pos:
                    pos = 0  # rotated / truncated
                if size > pos:
                    with path.open("r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(pos)
                        for line in fh:
                            formatted = format_log_line(line, color=color, source=label)
                            if formatted is not None:
                                print(formatted, file=out, flush=True)
                        positions[key] = fh.tell()
                else:
                    positions[key] = pos
            time.sleep(poll_s)
    except KeyboardInterrupt:
        return 0


def header_line(sources: Iterable[tuple[str, Path]], *, color: bool = True) -> str:
    """One-line banner listing paths being watched."""
    parts = [f"{label}={path}" for label, path in sources]
    text = "watching: " + "  ".join(parts)
    return _paint(f"# {text}", _DIM, color=color)
