"""Provider credential discovery (Grok OAuth preferred for xAI)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hark.paths import grok_auth_path


@dataclass
class AuthStatus:
    name: str
    available: bool
    source: str | None = None  # grok_oauth | env | config | none
    detail: str = ""
    # token is never included in doctor JSON by default


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def extract_grok_access_token(auth_path: Path | None = None) -> tuple[str | None, str]:
    """Return (token, source_detail) from ~/.grok/auth.json if usable.

    Prefer session/access tokens over static API keys when both exist.
    Never log the token.
    """
    path = auth_path or grok_auth_path()
    if not path.is_file():
        return None, "missing ~/.grok/auth.json (run: grok login)"

    data = _read_json(path)
    if not isinstance(data, dict):
        return None, "auth.json is not a JSON object"

    now = time.time()
    best_token: str | None = None
    best_kind = ""

    # Common shapes: map of issuer::client_id -> {key/access_token/token, expires...}
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        token = (
            entry.get("access_token")
            or entry.get("token")
            or entry.get("key")
            or entry.get("session_token")
        )
        if not token or not isinstance(token, str):
            continue
        exp = entry.get("expires_at") or entry.get("expiry") or entry.get("exp")
        if isinstance(exp, (int, float)) and exp < now - 60:
            continue
        # Prefer JWT-looking access tokens (eyJ...) over short API keys when both present
        kind = "access_token" if token.startswith("eyJ") else "api_key"
        if best_token is None or (kind == "access_token" and best_kind != "access_token"):
            best_token = token
            best_kind = kind

    if best_token:
        return best_token, f"grok_oauth ({best_kind} from {path})"

    return None, "auth.json present but no usable token (try: grok login)"


def xai_auth() -> AuthStatus:
    token, detail = extract_grok_access_token()
    if token:
        return AuthStatus(name="xai", available=True, source="grok_oauth", detail=detail)
    env = os.environ.get("XAI_API_KEY")
    if env:
        return AuthStatus(
            name="xai",
            available=True,
            source="env",
            detail="XAI_API_KEY set",
        )
    return AuthStatus(
        name="xai",
        available=False,
        source=None,
        detail=f"{detail}; or set XAI_API_KEY",
    )


def openai_auth() -> AuthStatus:
    if os.environ.get("OPENAI_API_KEY"):
        return AuthStatus(
            name="openai", available=True, source="env", detail="OPENAI_API_KEY set"
        )
    return AuthStatus(
        name="openai", available=False, source=None, detail="set OPENAI_API_KEY"
    )


def google_auth() -> AuthStatus:
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        which = "GEMINI_API_KEY" if os.environ.get("GEMINI_API_KEY") else "GOOGLE_API_KEY"
        return AuthStatus(
            name="google", available=True, source="env", detail=f"{which} set"
        )
    return AuthStatus(
        name="google",
        available=False,
        source=None,
        detail="set GEMINI_API_KEY or GOOGLE_API_KEY",
    )


def minimax_auth() -> AuthStatus:
    if os.environ.get("MINIMAX_API_KEY"):
        return AuthStatus(
            name="minimax", available=True, source="env", detail="MINIMAX_API_KEY set"
        )
    return AuthStatus(
        name="minimax", available=False, source=None, detail="set MINIMAX_API_KEY"
    )


def anthropic_auth() -> AuthStatus:
    # No public STT; still report API key for orchestrator awareness
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AuthStatus(
            name="anthropic",
            available=False,
            source="env",
            detail="key set but public STT/TTS unsupported for hark",
        )
    return AuthStatus(
        name="anthropic",
        available=False,
        source=None,
        detail="unsupported STT/TTS (use as orchestrator only)",
    )


def all_provider_status() -> list[AuthStatus]:
    return [
        xai_auth(),
        openai_auth(),
        google_auth(),
        minimax_auth(),
        anthropic_auth(),
    ]


def resolve_xai_token() -> str | None:
    token, _ = extract_grok_access_token()
    if token:
        return token
    return os.environ.get("XAI_API_KEY")
