from __future__ import annotations

import io
import math
import shutil
import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from hark.audio import playback
from hark.config import config_to_dict, load_config


def test_playback_speed_config_defaults_and_loads(tmp_path: Path) -> None:
    default = load_config(tmp_path / "missing.toml")
    assert default.tts.playback_speed == 1.0
    assert config_to_dict(default)["tts"]["playback_speed"] == 1.0

    path = tmp_path / "config.toml"
    path.write_text("[tts]\nplayback_speed = 1.25\n", encoding="utf-8")
    configured = load_config(path)
    assert configured.tts.playback_speed == 1.25
    assert not configured.warnings


@pytest.mark.parametrize(
    "value", ["0", "-1", "nan", "inf", '"fast"', "true"]
)
def test_invalid_playback_speed_falls_back_with_warning(
    tmp_path: Path, value: str
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f"[tts]\nplayback_speed = {value}\n", encoding="utf-8")
    configured = load_config(path)
    assert configured.tts.playback_speed == 1.0
    assert any("tts.playback_speed" in warning for warning in configured.warnings)


def test_atempo_filter_supports_speeds_outside_single_filter_range() -> None:
    assert playback._atempo_filter(1.25) == "atempo=1.25"
    assert playback._atempo_filter(4.0) == "atempo=2,atempo=2"
    assert playback._atempo_filter(0.25) == "atempo=0.5,atempo=0.5"


def test_play_audio_adjusts_before_duration_and_play(monkeypatch) -> None:
    transformed = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 8
    adjusted: list[tuple[bytes, str, int | None, float]] = []
    played: list[tuple[bytes, int]] = []

    def fake_adjust(data, *, fmt, sample_rate, playback_speed):
        adjusted.append((data, fmt, sample_rate, playback_speed))
        return transformed

    monkeypatch.setattr(playback, "_apply_playback_speed", fake_adjust)
    monkeypatch.setattr(playback, "estimate_duration_ms", lambda data, sr: 800)
    monkeypatch.setattr(playback, "_wav_to_pcm16", lambda data: (b"pcm", 24000))
    monkeypatch.setattr(
        playback, "_play_pcm16", lambda pcm, sample_rate: played.append((pcm, sample_rate))
    )

    result = playback.play_audio(
        b"raw pcm", sample_rate=24000, playback_speed=1.25, exclusive=False
    )

    assert adjusted == [(b"raw pcm", "pcm", 24000, 1.25)]
    assert played == [(b"pcm", 24000)]
    assert result.duration_ms == 800
    assert result.format == "wav"


def test_default_playback_speed_does_not_require_ffmpeg(monkeypatch) -> None:
    monkeypatch.setattr(
        playback,
        "_apply_playback_speed",
        lambda *a, **k: pytest.fail("default speed should not transform audio"),
    )
    monkeypatch.setattr(playback, "estimate_duration_ms", lambda data, sr: 1)
    monkeypatch.setattr(playback, "_play_pcm16", lambda pcm, sample_rate: None)

    playback.play_audio(b"\x00\x00", sample_rate=24000, exclusive=False)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is optional")
def test_ffmpeg_speed_adjustment_preserves_pitch_and_changes_duration() -> None:
    sample_rate = 24000
    frames = b"".join(
        struct.pack(
            "<h", int(5000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        )
        for index in range(sample_rate)
    )
    source = io.BytesIO()
    with wave.open(source, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)

    adjusted = playback._apply_playback_speed(
        source.getvalue(), fmt="wav", sample_rate=None, playback_speed=1.25
    )

    assert 780 <= playback.estimate_duration_ms(adjusted) <= 820
    with wave.open(io.BytesIO(adjusted), "rb") as wav:
        output_rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    frequencies = np.fft.rfftfreq(samples.size, d=1 / output_rate)
    dominant_hz = frequencies[int(np.argmax(np.abs(np.fft.rfft(samples))))]
    assert dominant_hz == pytest.approx(440, abs=3)
