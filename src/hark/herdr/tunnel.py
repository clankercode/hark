"""SSH Unix-socket tunnel helper for remote Herdr sessions."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from hark.paths import cache_dir


@dataclass
class Tunnel:
    session_id: str
    ssh: str
    local_socket: Path
    remote_socket: str
    proc: subprocess.Popen | None = None

    def start(self) -> Path:
        self.local_socket.parent.mkdir(parents=True, exist_ok=True)
        if self.local_socket.exists():
            try:
                self.local_socket.unlink()
            except OSError:
                pass
        # ssh -N -L local:remote
        # For Unix sockets: ssh -L /local.sock:/remote.sock
        cmd = [
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
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        # wait briefly for socket
        for _ in range(50):
            if self.local_socket.exists():
                return self.local_socket
            if self.proc.poll() is not None:
                err = (self.proc.stderr.read() if self.proc.stderr else b"").decode()
                raise RuntimeError(f"ssh tunnel failed: {err[:400]}")
            time.sleep(0.1)
        raise RuntimeError(f"ssh tunnel timeout for {self.session_id}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.local_socket.exists():
            try:
                self.local_socket.unlink()
            except OSError:
                pass


def ensure_tunnel(
    session_id: str,
    ssh: str,
    *,
    remote_socket: str | None = None,
) -> Tunnel:
    remote = remote_socket or f"{os.path.expanduser('~')}/.config/herdr/herdr.sock"
    # remote path is on remote host — use absolute common default
    if remote.startswith("~"):
        remote = "/home/%h/.config/herdr/herdr.sock"  # may need operator override
    # Prefer explicit remote home via config; default standard path string for remote
    if "%h" in remote:
        remote = "~/.config/herdr/herdr.sock"
    local = cache_dir() / "tunnels" / f"{session_id}.sock"
    t = Tunnel(
        session_id=session_id,
        ssh=ssh,
        local_socket=local,
        remote_socket=remote if not remote.startswith("~") else "~/.config/herdr/herdr.sock",
    )
    # OpenSSH supports remote unix path as-is with ~
    t.remote_socket = remote_socket or "~/.config/herdr/herdr.sock"
    t.start()
    return t
