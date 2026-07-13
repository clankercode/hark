"""B038: every STT upload emits stt.request / stt.response on system.jsonl."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from hark.audio.capture import CaptureResult, write_wav_bytes
from hark.config import HarkConfig, ListenConfig
from hark.providers.base import ProviderError, Transcript
from hark.speech import _estimate_wav_audio_ms, _transcribe_logged, run_listen
from hark.usage import UsageStore


def _cap(
    *,
    duration_ms: int = 800,
    peak_rms: float = 0.02,
    text_pcm_ms: int | None = None,
) -> CaptureResult:
    ms = text_pcm_ms if text_pcm_ms is not None else duration_ms
    pcm = b"\x00\x00" * max(1, int(16 * ms))  # 16 samples/ms @ 16 kHz
    return CaptureResult(
        pcm16=pcm,
        sample_rate=16000,
        duration_ms=duration_ms,
        speech_ms=duration_ms,
        wait_speech_ms=40,
        peak_rms=peak_rms,
        peak_db=-34.0,
    )


@dataclass
class _FakeStt:
    name: str = "fake"
    texts: list[str] | None = None
    calls: int = 0
    fail_on: int | None = None  # 1-based call index to raise on
    last_wav: bytes | None = None

    def __post_init__(self) -> None:
        self.texts = list(self.texts or [])

    def transcribe(self, wav_bytes: bytes, *, language: str | None = None) -> Transcript:
        del language
        self.calls += 1
        self.last_wav = wav_bytes
        if self.fail_on is not None and self.calls == self.fail_on:
            raise ProviderError("simulated STT failure")
        text = self.texts.pop(0) if self.texts else ""
        return Transcript(text=text, provider=self.name)


class _NullCtx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_listen_infra(monkeypatch, stt: _FakeStt, caps: list[CaptureResult]):
    monkeypatch.setattr("hark.speech.resolve_stt", lambda *a, **k: stt)
    cap_iter = iter(caps)

    def fake_capture(**kwargs):
        del kwargs
        try:
            return next(cap_iter)
        except StopIteration as exc:
            raise TimeoutError("no more capture fixtures") from exc

    monkeypatch.setattr("hark.speech.capture_utterance", fake_capture)
    monkeypatch.setattr("hark.speech.pause_ambient_for_mic", lambda **k: _NullCtx())
    monkeypatch.setattr("hark.speech.MicLease", lambda *a, **k: _NullCtx())
    monkeypatch.setattr("hark.speech.BusySection", lambda *a, **k: _NullCtx())
    monkeypatch.setattr("hark.speech.register_active_listen", lambda *a, **k: None)
    monkeypatch.setattr("hark.speech.clear_active_listen", lambda *a, **k: None)
    monkeypatch.setattr("hark.speech.consume_listen_action", lambda *a, **k: None)
    monkeypatch.setattr("hark.speech.poll_listen_action", lambda *a, **k: None)
    monkeypatch.setattr("hark.speech.play_record_start", lambda: None)
    monkeypatch.setattr("hark.speech.play_record_stop", lambda: None)
    monkeypatch.setattr("hark.speech.configure_cues_from_config", lambda cfg: None)
    monkeypatch.setattr("hark.speech.time.sleep", lambda s: None)


def test_estimate_wav_audio_ms():
    wav = write_wav_bytes(b"\x00\x00" * 16000, 16000)  # 1s
    assert _estimate_wav_audio_ms(wav) == 1000
    assert _estimate_wav_audio_ms(b"") == 0


def test_transcribe_logged_emits_request_and_response(monkeypatch):
    logs: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "hark.speech.syslog",
        lambda event, **data: logs.append((event, data)),
    )
    stt = _FakeStt(texts=["hello there"])
    wav = write_wav_bytes(b"\x00\x00" * 3200, 16000)  # 200ms
    tr, latency_ms = _transcribe_logged(
        stt,
        wav,
        stream_id="s-test",
        seq=1,
        mode="silence",
        purpose="silence",
        audio_ms=200,
    )
    assert tr.text == "hello there"
    assert latency_ms >= 0
    assert [e for e, _ in logs] == ["stt.request", "stt.response"]
    req = logs[0][1]
    assert req["stream_id"] == "s-test"
    assert req["seq"] == 1
    assert req["provider"] == "fake"
    assert req["bytes"] == len(wav)
    assert req["audio_ms"] == 200
    assert req["mode"] == "silence"
    assert req["purpose"] == "silence"
    resp = logs[1][1]
    assert resp["ok"] is True
    assert resp["stream_id"] == "s-test"
    assert resp["seq"] == 1
    assert resp["latency_ms"] >= 0
    assert resp["chars"] == len("hello there")
    assert resp["empty"] is False
    assert "hello" in resp["text"]


def test_transcribe_logged_error_path(monkeypatch):
    logs: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "hark.speech.syslog",
        lambda event, **data: logs.append((event, data)),
    )
    stt = _FakeStt(fail_on=1)
    with pytest.raises(ProviderError, match="simulated"):
        _transcribe_logged(
            stt,
            b"RIFF" + b"\x00" * 40,
            stream_id="s-err",
            seq=3,
            mode="radio",
            purpose="radio",
        )
    assert [e for e, _ in logs] == ["stt.request", "stt.response"]
    resp = logs[1][1]
    assert resp["ok"] is False
    assert resp["seq"] == 3
    assert resp["stream_id"] == "s-err"
    assert "simulated" in (resp.get("error") or "")
    assert resp["level"] == "error" or logs[1][1].get("ok") is False


def test_silence_listen_logs_stt_request_response(monkeypatch, tmp_path):
    stt = _FakeStt(texts=["option two"])
    _patch_listen_infra(monkeypatch, stt, [_cap(duration_ms=900)])
    logs: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "hark.speech.syslog",
        lambda event, **data: logs.append((event, data)),
    )
    monkeypatch.setattr(
        "hark.speech.UsageStore",
        lambda: UsageStore(tmp_path / "usage.jsonl"),
    )
    cfg = HarkConfig(
        listen=ListenConfig(empty_stt_retry=False, empty_stt_nudge=False),
    )
    result = run_listen(
        cfg,
        stream_id="s-silence-1",
        post_tts_guard_s=0,
    )
    assert result.text == "option two"
    reqs = [d for e, d in logs if e == "stt.request"]
    resps = [d for e, d in logs if e == "stt.response"]
    assert len(reqs) == 1
    assert len(resps) == 1
    assert reqs[0]["stream_id"] == "s-silence-1"
    assert reqs[0]["seq"] == 1
    assert reqs[0]["provider"] == "fake"
    assert reqs[0]["purpose"] == "silence"
    assert reqs[0]["audio_ms"] == 900
    assert reqs[0]["bytes"] > 0
    assert resps[0]["ok"] is True
    assert resps[0]["latency_ms"] >= 0
    assert resps[0]["seq"] == 1


def test_radio_partials_log_every_stt_upload(monkeypatch, tmp_path):
    """Radio interim STT calls must hit syslog even before end phrase."""
    stt = _FakeStt(
        texts=[
            "please open the pull request",
            "please open the pull request for auth",
            "please open the pull request for auth okay hark send",
        ]
    )
    _patch_listen_infra(
        monkeypatch,
        stt,
        [_cap(duration_ms=500), _cap(duration_ms=600), _cap(duration_ms=700)],
    )
    logs: list[tuple[str, dict]] = []
    partials: list[dict] = []

    monkeypatch.setattr(
        "hark.speech.syslog",
        lambda event, **data: logs.append((event, data)),
    )
    monkeypatch.setattr(
        "hark.speech.UsageStore",
        lambda: UsageStore(tmp_path / "usage.jsonl"),
    )

    def on_partial(ev: dict) -> None:
        partials.append(ev)

    cfg = HarkConfig(
        listen=ListenConfig(
            end_mode="radio",
            stream_partials=True,
            end_phrases=("okay hark send", "hark send"),
        ),
    )
    result = run_listen(
        cfg,
        end_mode="radio",
        stream_id="s-radio-1",
        post_tts_guard_s=0,
        on_partial=on_partial,
    )
    assert "pull request" in result.text.lower()
    assert stt.calls == 3

    reqs = [d for e, d in logs if e == "stt.request"]
    resps = [d for e, d in logs if e == "stt.response"]
    assert len(reqs) == 3, f"expected 3 STT uploads, got {len(reqs)}: {logs}"
    assert len(resps) == 3
    for i, (req, resp) in enumerate(zip(reqs, resps), start=1):
        assert req["stream_id"] == "s-radio-1"
        assert req["seq"] == i
        assert req["provider"] == "fake"
        assert req["mode"] == "radio"
        assert req["purpose"] == "radio"
        assert req["bytes"] > 0
        assert req["audio_ms"] >= 0
        assert resp["ok"] is True
        assert resp["seq"] == i
        assert resp["stream_id"] == "s-radio-1"
        assert resp["latency_ms"] >= 0

    # Partials correlate via stream_id + stt_seq
    listen_partials = [d for e, d in logs if e == "listen.partial"]
    assert len(listen_partials) >= 1
    assert len(partials) >= 1
    for lp in listen_partials:
        assert lp["stream_id"] == "s-radio-1"
        assert "stt_seq" in lp
        assert 1 <= lp["stt_seq"] <= 3
    for ev in partials:
        assert ev["stream_id"] == "s-radio-1"
        assert "stt_seq" in ev
        # ambient.partial kind by default
        assert ev["kind"] == "ambient.partial"
        assert ev["partial"] is True


def test_radio_stt_error_logs_response_ok_false(monkeypatch, tmp_path):
    stt = _FakeStt(texts=["x"], fail_on=1)
    _patch_listen_infra(monkeypatch, stt, [_cap()])
    logs: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "hark.speech.syslog",
        lambda event, **data: logs.append((event, data)),
    )
    monkeypatch.setattr(
        "hark.speech.UsageStore",
        lambda: UsageStore(tmp_path / "usage.jsonl"),
    )
    cfg = HarkConfig(listen=ListenConfig(end_mode="radio"))
    with pytest.raises(ProviderError, match="simulated"):
        run_listen(
            cfg,
            end_mode="radio",
            stream_id="s-fail",
            post_tts_guard_s=0,
        )
    resps = [d for e, d in logs if e == "stt.response"]
    assert len(resps) == 1
    assert resps[0]["ok"] is False
    assert resps[0]["stream_id"] == "s-fail"
    assert resps[0]["seq"] == 1
