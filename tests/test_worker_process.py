"""PID-reuse-safe worker identity and signalling regression tests (B127)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import hark.worker_process as worker_process


@pytest.mark.parametrize(
    ("argv", "role"),
    [
        (["hark", "ambient"], "ambient"),
        (["/venv/bin/hark", "watch", "--for-monitor"], "watch"),
        (["python3", "/venv/bin/hark", "ambient"], "ambient"),
        (["python", "-m", "hark", "watch", "--session", "lab"], "watch"),
        (["/usr/bin/uv", "run", "hark", "ambient"], "ambient"),
    ],
)
def test_worker_role_accepts_real_launch_shapes(argv: list[str], role: str):
    assert worker_process.worker_role_from_argv(argv) == role


@pytest.mark.parametrize(
    "argv",
    [
        ["bash", "-c", "sleep 60", "hark", "ambient"],
        ["python", "-c", "import time", "hark", "watch"],
        ["python", "script.py", "hark", "ambient"],
        ["uv", "tool", "hark", "watch"],
    ],
)
def test_worker_role_rejects_unrelated_trailing_hark_args(argv: list[str]):
    assert worker_process.worker_role_from_argv(argv) is None


def spawn_process(
    directory: Path, *, role: str | None = None
) -> subprocess.Popen[bytes]:
    if role:
        launcher = directory / "hark"
        launcher.write_text(
            "#!/usr/bin/env python3\n"
            "import signal\n"
            "import time\n"
            "def stop(*_args):\n"
            "    raise SystemExit(0)\n"
            "signal.signal(signal.SIGTERM, stop)\n"
            "while True:\n"
            "    time.sleep(1)\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        child = subprocess.Popen([str(launcher), role], start_new_session=True)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if worker_process.inspect_worker(child.pid, expected_role=role) is not None:
                return child
            time.sleep(0.01)
        kill_child(child)
        raise AssertionError(f"worker argv did not become ready for role {role}")
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )


def kill_child(child: subprocess.Popen[bytes]) -> None:
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except OSError:
            child.kill()
    child.wait(timeout=2)


def test_legacy_worker_is_migrated_with_role_and_start_time(tmp_path: Path):
    child = spawn_process(tmp_path, role="ambient")
    path = tmp_path / "mode-a.pids"
    try:
        path.write_text(f"pid={child.pid}\n", encoding="utf-8")
        records = worker_process.collect_worker_records(path)
        assert [(record.pid, record.role) for record in records] == [
            (child.pid, "ambient")
        ]
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored == {
            "pid": child.pid,
            "role": "ambient",
            "start_time": records[0].start_time,
            "version": 1,
        }
    finally:
        kill_child(child)


def test_live_unrelated_legacy_pid_is_removed_without_signal(tmp_path: Path):
    child = spawn_process(tmp_path)
    path = tmp_path / "mode-a.pids"
    try:
        path.write_text(f"{child.pid}\n", encoding="utf-8")
        assert worker_process.collect_worker_records(path) == []
        assert child.poll() is None
        assert not path.exists()
    finally:
        kill_child(child)


def test_unrelated_suffix_is_ignored_by_migration_and_discovery(tmp_path: Path):
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
            "hark",
            "ambient",
        ],
        start_new_session=True,
    )
    path = tmp_path / "mode-a.pids"
    try:
        path.write_text(f"{child.pid}\n", encoding="utf-8")
        records = worker_process.collect_worker_records(path, discover=True)
        assert child.pid not in {record.pid for record in records}
        assert child.poll() is None
    finally:
        kill_child(child)


def test_orphan_discovery_records_untracked_worker(tmp_path: Path):
    child = spawn_process(tmp_path, role="watch")
    path = tmp_path / "mode-a.pids"
    try:
        records = worker_process.collect_worker_records(path, discover=True)
        matching = [record for record in records if record.pid == child.pid]
        assert len(matching) == 1
        assert matching[0].role == "watch"
        assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])[
            "start_time"
        ]
    finally:
        kill_child(child)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda record: worker_process.WorkerRecord(
            pid=record.pid, start_time="reused-pid-start-time", role=record.role
        ),
        lambda record: worker_process.WorkerRecord(
            pid=record.pid, start_time=record.start_time, role="watch"
        ),
    ],
    ids=["reused-pid", "role-mismatch"],
)
def test_mismatched_structured_record_is_removed_without_signal(
    tmp_path: Path,
    mutation,
):
    child = spawn_process(tmp_path, role="ambient")
    path = tmp_path / "mode-a.pids"
    try:
        actual = worker_process.inspect_worker(child.pid)
        assert actual is not None
        worker_process.write_worker_records(path, [mutation(actual)])
        records = worker_process.collect_worker_records(path)
        assert records == []
        assert child.poll() is None
        assert not path.exists()
    finally:
        kill_child(child)


def test_malformed_and_stale_entries_are_removed(tmp_path: Path):
    path = tmp_path / "mode-a.pids"
    path.write_text(
        "\n".join(
            [
                "not-json-or-pid",
                '{"pid":true,"role":"watch","start_time":"1","version":1}',
                '{"pid":123,"role":[],"start_time":"1","version":1}',
                '{"pid":999999999,"role":"watch","start_time":"1","version":1}',
            ]
        ),
        encoding="utf-8",
    )
    assert worker_process.collect_worker_records(path) == []
    assert not path.exists()


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGKILL])
def test_signal_reverifies_after_opening_pidfd(
    monkeypatch: pytest.MonkeyPatch, sig: int
):
    record = worker_process.WorkerRecord(
        pid=os.getpid(), start_time="old", role="watch"
    )
    read_fd, write_fd = os.pipe()
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(worker_process.os, "pidfd_open", lambda _pid: read_fd)
    monkeypatch.setattr(
        worker_process.signal,
        "pidfd_send_signal",
        lambda fd, sig: sent.append((fd, sig)),
    )
    monkeypatch.setattr(worker_process, "record_matches_process", lambda _record: False)
    try:
        assert worker_process.signal_worker(record, sig) is False
        assert sent == []
    finally:
        os.close(write_fd)


def test_shell_signal_adapter_delegates_to_identity_module(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    script = repo / "scripts" / "run-mode-a.sh"
    trace = tmp_path / "trace"
    command = f"""
set -euo pipefail
export HARK_RUN_MODE_A_SOURCE_ONLY=1
export XDG_STATE_HOME={tmp_path!s}
source {script!s}
worker_identity() {{ printf '%s\\n' "$*" >> {trace!s}; }}
signal_pids TERM 123 456
"""
    subprocess.run(
        ["bash", "-c", command],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    expected_pidfile = tmp_path / "hark" / "mode-a.pids"
    assert trace.read_text(encoding="utf-8").strip() == (
        f"signal {expected_pidfile} TERM --discover"
    )


def test_shell_stop_retains_pidfile_when_identity_collection_fails(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    script = repo / "scripts" / "run-mode-a.sh"
    state = tmp_path / "state"
    pidfile = state / "hark" / "mode-a.pids"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text("sentinel\n", encoding="utf-8")
    command = f"""
set -euo pipefail
export HARK_RUN_MODE_A_SOURCE_ONLY=1
export XDG_STATE_HOME={state!s}
source {script!s}
worker_identity() {{ return 42; }}
set +e
graceful_stop 0 stop
status=$?
set -e
printf '%s\n' "$status"
"""
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "1"
    assert "refusing to stop" in result.stderr
    assert pidfile.read_text(encoding="utf-8") == "sentinel\n"


def test_shell_start_refuses_when_initial_identity_collection_fails(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    script = repo / "scripts" / "run-mode-a.sh"
    state = tmp_path / "state"
    pidfile = state / "hark" / "mode-a.pids"
    pidfile.parent.mkdir(parents=True)
    pidfile.write_text("sentinel\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
    uv.chmod(0o755)
    env = os.environ.copy()
    env["XDG_STATE_HOME"] = str(state)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [str(script), "--no-ambient"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert "refusing to start" in result.stderr
    assert pidfile.read_text(encoding="utf-8") == "sentinel\n"


def test_shell_post_spawn_collection_failure_retains_legacy_pid(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    script = repo / "scripts" / "run-mode-a.sh"
    state = tmp_path / "state"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    count = tmp_path / "collect-count"
    uv = fake_bin / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        'if printf \'%s\\n\' "$*" | grep -q hark.worker_process; then\n'
        f"  n=$(cat {count!s} 2>/dev/null || echo 0)\n"
        "  n=$((n + 1))\n"
        f"  printf '%s\\n' \"$n\" > {count!s}\n"
        "  [ \"$n\" -eq 1 ] && exit 0\n"
        "  exit 42\n"
        "fi\n"
        "case \"$*\" in\n"
        "  *'python -c'*) exit 0 ;;\n"
        "esac\n"
        "exec sleep 60\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)
    env = os.environ.copy()
    env["XDG_STATE_HOME"] = str(state)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [str(script), "--no-ambient"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    pidfile = state / "hark" / "mode-a.pids"
    recorded = int(pidfile.read_text(encoding="utf-8").strip())
    try:
        assert result.returncode != 0
        assert "retaining legacy ownership" in result.stderr
        os.kill(recorded, 0)
    finally:
        try:
            os.kill(recorded, signal.SIGKILL)
        except ProcessLookupError:
            pass
