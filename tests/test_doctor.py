"""hark doctor — media ducking readiness (B047) soft checks."""

from __future__ import annotations

import io
import json

from hark.config import AudioConfig, HarkConfig
from hark.doctor import _media_duck_report, run_doctor
from hark.exitcodes import OK


def _cfg(**audio_kw) -> HarkConfig:
    return HarkConfig(audio=AudioConfig(**audio_kw), sessions=[])


def test_media_duck_report_ready(monkeypatch):
    monkeypatch.setattr(
        "hark.doctor.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in ("pactl", "playerctl") else None,
    )
    report = _media_duck_report(_cfg())
    assert report["status"] == "ready"
    assert report["pactl_ok"] is True
    assert report["playerctl_ok"] is True
    assert report["duck_level"] == 0.15
    assert report["duck_media_during_tts"] is True
    assert report["duck_media_during_stt"] is True
    assert report["pause_media_during_stt"] is True
    assert report["warnings"] == []


def test_media_duck_report_pactl_missing_degraded(monkeypatch):
    monkeypatch.setattr(
        "hark.doctor.shutil.which",
        lambda name: "/usr/bin/playerctl" if name == "playerctl" else None,
    )
    report = _media_duck_report(_cfg())
    assert report["status"] == "degraded"
    assert report["pactl_ok"] is False
    assert report["playerctl_ok"] is True
    assert any("pactl missing" in w for w in report["warnings"])
    # Soft only — does not imply hard doctor failure


def test_media_duck_report_playerctl_missing_warns(monkeypatch):
    monkeypatch.setattr(
        "hark.doctor.shutil.which",
        lambda name: "/usr/bin/pactl" if name == "pactl" else None,
    )
    report = _media_duck_report(_cfg())
    assert report["status"] == "ready"  # volume duck still works
    assert report["pactl_ok"] is True
    assert report["playerctl_ok"] is False
    assert any("playerctl missing" in w for w in report["warnings"])


def test_media_duck_report_disabled_when_all_off(monkeypatch):
    monkeypatch.setattr("hark.doctor.shutil.which", lambda _name: None)
    report = _media_duck_report(
        _cfg(
            duck_media_during_tts=False,
            duck_media_during_stt=False,
            pause_media_during_tts=False,
            pause_media_during_stt=False,
            media_check_mpris=False,
        )
    )
    assert report["status"] == "disabled"
    # No tool warnings when ducking is fully off and MPRIS unused
    assert report["warnings"] == []


def test_run_doctor_includes_media_duck_soft(monkeypatch):
    """Missing pactl → warn in human + JSON; still exit OK when herdr ok."""
    monkeypatch.setattr(
        "hark.doctor.shutil.which",
        lambda name: None if name in ("pactl", "playerctl", "herdr") else f"/bin/{name}",
    )
    # No herdr sessions → herdr_ok stays True
    cfg = _cfg()
    out = io.StringIO()
    err = io.StringIO()
    code = run_doctor(cfg, as_json=False, out=out, err=err)
    assert code == OK
    text = out.getvalue()
    assert "media duck:" in text
    assert "degraded" in text
    assert "pactl" in text.lower()
    # overall may be DEGRADED from speech keys, but exit is not HERDR from ducking
    assert "warn:" in text


def test_run_doctor_json_media_duck(monkeypatch):
    monkeypatch.setattr(
        "hark.doctor.shutil.which",
        lambda name: f"/usr/bin/{name}" if name == "pactl" else None,
    )
    out = io.StringIO()
    code = run_doctor(_cfg(), as_json=True, out=out, err=io.StringIO())
    assert code == OK
    report = json.loads(out.getvalue())
    assert "media_duck" in report
    assert report["media_duck"]["pactl_ok"] is True
    assert report["media_duck"]["status"] == "ready"
    # Soft warnings must not flip overall herdr/ok solely for playerctl
    assert report["ok"] is True
