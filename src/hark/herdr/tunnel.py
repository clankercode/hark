"""Reusable SSH Unix-socket tunnels for configured remote Herdr sessions."""

from __future__ import annotations

import hashlib
import os
import socket
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from hark.paths import cache_dir


_DEFAULT_REMOTE_SOCKET = "~/.config/herdr/herdr.sock"


def tunnel_socket_path(
    session_id: str,
    ssh: str,
    *,
    remote_socket: str | None = None,
) -> Path:
    """Return the deterministic local socket for one exact remote transport."""
    remote = remote_socket or _DEFAULT_REMOTE_SOCKET
    digest = hashlib.sha256(f"{ssh}\0{remote}".encode()).hexdigest()[:12]
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    # A process owns and cleans only its own path. This prevents one Hark
    # process from unlinking another process's active forwarding socket.
    return cache_dir() / "tunnels" / f"{safe_id}-{os.getpid()}-{digest}.sock"


def _socket_is_live(path: Path) -> bool:
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.2)
        probe.connect(str(path))
        return True
    except OSError:
        return False
    finally:
        probe.close()


@dataclass
class Tunnel:
    session_id: str
    ssh: str
    local_socket: Path
    remote_socket: str
    proc: subprocess.Popen[bytes] | None = None
    owns_socket: bool = True

    def start(self) -> Path:
        self.local_socket.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(self.local_socket):
            mode = self.local_socket.lstat().st_mode
            if not stat.S_ISSOCK(mode):
                raise RuntimeError(
                    f"refusing non-socket tunnel path for {self.session_id!r}: "
                    f"{self.local_socket}"
                )
            if _socket_is_live(self.local_socket):
                raise RuntimeError(
                    f"refusing unowned live tunnel path for {self.session_id!r}: "
                    f"{self.local_socket}"
                )
            self.local_socket.unlink()

        command = [
            "ssh",
            "-N",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "BatchMode=yes",
            "-L",
            f"{self.local_socket}:{self.remote_socket}",
            self.ssh,
        ]
        self.proc = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            for _ in range(50):
                if self.proc.poll() is not None:
                    raw = self.proc.stderr.read() if self.proc.stderr else b""
                    error = raw.decode(errors="replace")[:400]
                    raise RuntimeError(
                        f"SSH tunnel failed for {self.session_id!r}: "
                        f"{error or f'exit {self.proc.returncode}'}"
                    )
                if os.path.lexists(self.local_socket):
                    mode = self.local_socket.lstat().st_mode
                    if not stat.S_ISSOCK(mode):
                        raise RuntimeError(
                            f"SSH tunnel path for {self.session_id!r} is not a Unix socket"
                        )
                    return self.local_socket
                time.sleep(0.1)
            raise RuntimeError(f"SSH tunnel timeout for {self.session_id!r}")
        except BaseException:
            self.stop()
            raise

    def is_live(self) -> bool:
        return (
            self.proc is not None
            and self.proc.poll() is None
            and os.path.lexists(self.local_socket)
            and stat.S_ISSOCK(self.local_socket.lstat().st_mode)
            and _socket_is_live(self.local_socket)
        )

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)
        if self.owns_socket and os.path.lexists(self.local_socket):
            try:
                if stat.S_ISSOCK(self.local_socket.lstat().st_mode):
                    self.local_socket.unlink()
            except FileNotFoundError:
                pass


@dataclass
class _TunnelRecord:
    tunnel: Tunnel
    references: int = 1


@dataclass
class TunnelLease:
    """A reference-counted handle to one process-local tunnel record."""

    _key: tuple[str, str, str]
    _record: _TunnelRecord
    _released: bool = False

    @property
    def local_socket(self) -> Path:
        return self._record.tunnel.local_socket

    def stop(self) -> None:
        with _TUNNEL_LOCK:
            if self._released:
                return
            self._released = True
            record = _TUNNELS.get(self._key)
            if record is not self._record:
                return
            record.references -= 1
            if record.references > 0:
                return
            try:
                record.tunnel.stop()
            except BaseException:
                record.references = 1
                self._released = False
                raise
            _TUNNELS.pop(self._key, None)


_TUNNEL_LOCK = threading.RLock()
_TUNNELS: dict[tuple[str, str, str], _TunnelRecord] = {}


def ensure_tunnel(
    session_id: str,
    ssh: str,
    *,
    remote_socket: str | None = None,
) -> TunnelLease:
    """Establish or reuse the tunnel for one exact configured transport."""
    remote = remote_socket or _DEFAULT_REMOTE_SOCKET
    key = (session_id, ssh, remote)
    with _TUNNEL_LOCK:
        record = _TUNNELS.get(key)
        if record is not None:
            if record.tunnel.is_live():
                record.references += 1
                return TunnelLease(key, record)
            # A dead cached process is never a reusable tunnel. Remove its
            # process-scoped socket before replacing the registry record.
            _TUNNELS.pop(key, None)
            try:
                record.tunnel.stop()
            except BaseException:
                _TUNNELS[key] = record
                raise

        tunnel = Tunnel(
            session_id=session_id,
            ssh=ssh,
            local_socket=tunnel_socket_path(
                session_id,
                ssh,
                remote_socket=remote,
            ),
            remote_socket=remote,
        )
        tunnel.start()
        record = _TunnelRecord(tunnel=tunnel)
        _TUNNELS[key] = record
        return TunnelLease(key, record)
