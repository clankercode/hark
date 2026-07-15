"""P1.M6.E4: bound listen ignores ambient.streaming TOML; post_wake still streams."""

from __future__ import annotations

from hark.answer_window import ListenSessionPolicy
from hark.answer_window.result import ListenResult
from hark.config import AmbientConfig, HarkConfig, ListenConfig
from hark.listen_control import clear_active_listen, read_active, register_active_listen
from hark.speech import _tts_defer_streaming_params, run_listen


def _fake_open(seen: list):
    def wrapper(policy, deps=None):
        seen.append(policy)
        return ListenResult(
            text="x",
            provider="fake",
            duration_ms=1,
            end_mode=str(
                policy.end_mode.value
                if hasattr(policy.end_mode, "value")
                else policy.end_mode
            ),
            stream_id=policy.stream_id,
        )

    return wrapper


def test_bound_radio_policy_ignores_ambient_streaming_toml(monkeypatch) -> None:
    """AC: fails if ambient leaks into bound profile (E4.T001)."""
    cfg = HarkConfig(
        ambient=AmbientConfig(streaming=True, streaming_ack_min_quiet_s=2.5),
        listen=ListenConfig(end_mode="radio"),
    )
    pol = ListenSessionPolicy.from_config(cfg, "bound_answer")
    assert pol.streaming is False

    seen: list = []
    monkeypatch.setattr(
        "hark.answer_window.open_window.open_answer_window",
        _fake_open(seen),
    )
    result = run_listen(cfg, end_mode="radio", post_tts_guard_s=0)
    assert result.text == "x"
    assert len(seen) == 1
    assert seen[0].streaming is False
    assert seen[0].profile == "bound_answer"


def test_post_wake_profile_streams_when_ambient_configured(monkeypatch) -> None:
    """AC: ambient path not regressed (E4.T002)."""
    cfg = HarkConfig(
        ambient=AmbientConfig(streaming=True, streaming_ack_min_quiet_s=2.5),
        listen=ListenConfig(end_mode="radio"),
    )
    pol = ListenSessionPolicy.from_config(cfg, "post_wake")
    assert pol.streaming is True
    assert pol.streaming_ack_min_quiet_s == 2.5

    seen: list = []
    monkeypatch.setattr(
        "hark.answer_window.open_window.open_answer_window",
        _fake_open(seen),
    )
    result = run_listen(cfg, profile="post_wake", end_mode="radio", post_tts_guard_s=0)
    assert result.text == "x"
    assert seen[0].streaming is True
    assert seen[0].profile == "post_wake"


def test_tts_defer_uses_active_listen_streaming_not_ambient_toml() -> None:
    """Bound active listen registers streaming=False; ambient TOML true must not quiet-gate."""
    cfg = HarkConfig(ambient=AmbientConfig(streaming=True, streaming_ack_min_quiet_s=2.5))
    clear_active_listen()
    try:
        register_active_listen(
            "bound-stream",
            mode="radio",
            streaming=False,
            streaming_ack_min_quiet_s=2.5,
        )
        active = read_active()
        assert active is not None
        assert active.get("streaming") is False
        streaming_ack, min_quiet = _tts_defer_streaming_params(cfg)
        assert streaming_ack is False
        assert min_quiet >= 0
    finally:
        clear_active_listen()


def test_tts_defer_streaming_when_active_listen_streams() -> None:
    cfg = HarkConfig(ambient=AmbientConfig(streaming=False))
    clear_active_listen()
    try:
        register_active_listen(
            "ambient-stream",
            mode="radio",
            streaming=True,
            streaming_ack_min_quiet_s=1.75,
        )
        streaming_ack, min_quiet = _tts_defer_streaming_params(cfg)
        assert streaming_ack is True
        assert min_quiet == 1.75
    finally:
        clear_active_listen()
