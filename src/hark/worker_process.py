"""Durable, PID-reuse-safe identity for ambient and watch workers.

``mode-a.pids`` used to contain bare process IDs.  A PID only identifies a
slot in the process table and may be reused, so it is not safe authority for a
later signal.  This module owns the versioned JSON-lines replacement and keeps
legacy files compatible by migrating only processes whose live command line is
recognisably a Hark ambient or watch worker.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

WORKER_ROLES = frozenset({"ambient", "watch"})
RECORD_VERSION = 1


@dataclass(frozen=True, order=True)
class WorkerRecord:
    """Identity of one specific lifetime of a Hark worker process."""

    pid: int
    start_time: str
    role: str
    version: int = RECORD_VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def _proc_stat(pid: int) -> tuple[str, str] | None:
    """Return ``(state, start_time_ticks)`` from Linux ``/proc/PID/stat``."""
    if pid <= 0:
        return None
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    # Field 2 (comm) is parenthesised and may itself contain spaces/parens.
    rparen = text.rfind(")")
    if rparen < 0:
        return None
    fields = text[rparen + 2 :].split()
    # fields[0] is field 3 (state); fields[19] is field 22 (starttime).
    if len(fields) <= 19 or fields[0] == "Z":
        return None
    return fields[0], fields[19]


def _proc_argv(pid: int) -> list[str] | None:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    return [
        part.decode("utf-8", errors="surrogateescape")
        for part in raw.split(b"\0")
        if part
    ]


def worker_role_from_argv(argv: Sequence[str]) -> str | None:
    """Classify only the launch shapes Hark itself uses for workers."""
    if not argv:
        return None
    if any("run-mode-a" in arg for arg in argv):
        return None

    executable = Path(argv[0]).name.lower()

    def role_at(index: int) -> str | None:
        if index >= len(argv):
            return None
        role = argv[index]
        return role if role in WORKER_ROLES else None

    # Direct console script or native entry point: `hark ROLE ...`.
    if executable == "hark":
        return role_at(1)

    is_python = executable.startswith(("python", "pypy"))
    if is_python:
        # Console script through a Python shebang: `python /path/hark ROLE ...`.
        if len(argv) > 1 and Path(argv[1]).name == "hark":
            return role_at(2)
        # Package entry point used by the daemon: `python -m hark ROLE ...`.
        if len(argv) > 2 and argv[1:3] == ["-m", "hark"]:
            return role_at(3)
        return None

    # Shell launcher wrapper: `uv run hark ROLE ...`.
    if (
        executable == "uv"
        and len(argv) > 2
        and argv[1] == "run"
        and Path(argv[2]).name == "hark"
    ):
        return role_at(3)
    return None


def inspect_worker(
    pid: int, *, expected_role: str | None = None
) -> WorkerRecord | None:
    """Inspect the current process occupying *pid*, if it is a Hark worker."""
    stat = _proc_stat(pid)
    argv = _proc_argv(pid)
    if stat is None or argv is None:
        return None
    role = worker_role_from_argv(argv)
    if role is None or (expected_role is not None and role != expected_role):
        return None
    return WorkerRecord(pid=pid, start_time=stat[1], role=role)


def capture_worker_identity(pid: int, *, role: str) -> WorkerRecord | None:
    """Capture a newly spawned, caller-owned worker before later validation."""
    if role not in WORKER_ROLES:
        raise ValueError(f"invalid worker role: {role}")
    stat = _proc_stat(pid)
    if stat is None:
        return None
    return WorkerRecord(pid=pid, start_time=stat[1], role=role)


def record_matches_process(record: WorkerRecord) -> bool:
    """Return whether *record* still names the same worker process lifetime."""
    return inspect_worker(record.pid, expected_role=record.role) == record


def _parse_stored_record(line: str) -> WorkerRecord | None:
    try:
        value = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    try:
        pid = value["pid"]
        start_time = value["start_time"]
        role = value["role"]
        version = value["version"]
    except KeyError:
        return None
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(start_time, str)
        or not start_time
        or not isinstance(role, str)
        or role not in WORKER_ROLES
        or not isinstance(version, int)
        or isinstance(version, bool)
        or version != RECORD_VERSION
    ):
        return None
    return WorkerRecord(pid=pid, start_time=start_time, role=role, version=version)


def _parse_legacy_pid(line: str) -> int | None:
    if line.startswith("pid="):
        line = line.split("=", 1)[1].strip()
    try:
        pid = int(line)
    except ValueError:
        return None
    return pid if pid > 0 else None


def read_worker_records(path: Path) -> list[WorkerRecord]:
    """Read structured identities without consulting the live process table."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records = {
        record.pid: record
        for line in lines
        if (record := _parse_stored_record(line.strip())) is not None
    }
    return sorted(records.values(), key=lambda record: record.pid)


def write_worker_records(path: Path, records: Iterable[WorkerRecord]) -> None:
    """Atomically replace *path* with deduplicated structured identities."""
    unique = {record.pid: record for record in records}
    ordered = sorted(unique.values(), key=lambda record: record.pid)
    if not ordered:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"{record.to_json()}\n" for record in ordered)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _discover_workers() -> list[WorkerRecord]:
    records: list[WorkerRecord] = []
    try:
        proc_entries = Path("/proc").iterdir()
    except OSError:
        return records
    for entry in proc_entries:
        if not entry.name.isdigit():
            continue
        record = inspect_worker(int(entry.name))
        if record is not None:
            records.append(record)
    return records


def collect_worker_records(
    path: Path,
    *,
    discover: bool = False,
    rewrite: bool = True,
) -> list[WorkerRecord]:
    """Load, validate, migrate, and optionally discover current workers.

    Bare legacy PIDs are accepted only when their current process shape is a
    Hark worker.  Malformed, dead, role-mismatched, or PID-reused entries are
    omitted.  Rewriting removes those unsafe entries and upgrades valid legacy
    entries to structured records.
    """
    records: dict[int, WorkerRecord] = {}
    try:
        original = path.read_text(encoding="utf-8")
    except OSError:
        original = ""
    lines = original.splitlines()

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        stored = _parse_stored_record(line)
        if stored is not None:
            if record_matches_process(stored):
                records[stored.pid] = stored
            continue
        legacy_pid = _parse_legacy_pid(line)
        if legacy_pid is not None:
            migrated = inspect_worker(legacy_pid)
            if migrated is not None:
                records[migrated.pid] = migrated

    if discover:
        for record in _discover_workers():
            records[record.pid] = record

    result = sorted(records.values(), key=lambda record: record.pid)
    canonical = "".join(f"{record.to_json()}\n" for record in result)
    if rewrite and (original != canonical or (not result and path.exists())):
        write_worker_records(path, result)
    return result


def signal_worker(record: WorkerRecord, sig: int) -> bool:
    """Verify identity immediately before safely signalling one worker.

    On Linux, a pidfd pins the process lifetime across verification and signal,
    closing the final PID-reuse race.  The fallback still re-verifies directly
    before ``kill`` for platforms lacking pidfd support.
    """
    pidfd_open = getattr(os, "pidfd_open", None)
    pidfd_send_signal = getattr(signal, "pidfd_send_signal", None)
    if pidfd_open is not None and pidfd_send_signal is not None:
        try:
            pidfd = pidfd_open(record.pid)
        except (OSError, ValueError):
            return False
        try:
            if not record_matches_process(record):
                return False
            try:
                pidfd_send_signal(pidfd, sig)
            except (OSError, ValueError):
                return False
            return True
        finally:
            os.close(pidfd)

    if not record_matches_process(record):
        return False
    try:
        os.kill(record.pid, sig)
    except OSError:
        return False
    return True


def signal_worker_records(
    records: Iterable[WorkerRecord], sig: int
) -> list[WorkerRecord]:
    return [record for record in records if signal_worker(record, sig)]


def _parse_signal(value: str) -> int:
    name = value.upper()
    if name.startswith("SIG"):
        name = name[3:]
    if name.isdigit():
        return int(name)
    try:
        return int(getattr(signal, f"SIG{name}"))
    except AttributeError as exc:
        raise argparse.ArgumentTypeError(f"unknown signal: {value}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect")
    collect.add_argument("pidfile", type=Path)
    collect.add_argument("--discover", action="store_true")
    send = sub.add_parser("signal")
    send.add_argument("pidfile", type=Path)
    send.add_argument("signal", type=_parse_signal)
    send.add_argument("--discover", action="store_true")
    args = parser.parse_args(argv)

    records = collect_worker_records(args.pidfile, discover=args.discover)
    if args.command == "signal":
        records = signal_worker_records(records, args.signal)
    for record in records:
        print(record.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
