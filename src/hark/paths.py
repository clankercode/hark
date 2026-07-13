"""XDG paths for config and state."""

from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "hark"
    return Path.home() / ".config" / "hark"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / "hark"
    return Path.home() / ".local" / "state" / "hark"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "hark"
    return Path.home() / ".cache" / "hark"


def default_config_path() -> Path:
    override = os.environ.get("HARK_CONFIG")
    if override:
        return Path(override)
    return config_dir() / "config.toml"


def grok_auth_path() -> Path:
    return Path.home() / ".grok" / "auth.json"


def default_herdr_socket() -> Path:
    override = os.environ.get("HERDR_SOCKET_PATH")
    if override:
        return Path(override)
    return Path.home() / ".config" / "herdr" / "herdr.sock"
