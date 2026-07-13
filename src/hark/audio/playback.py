"""Playback helpers."""

from __future__ import annotations

import io
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover
    sd = None  # type: ignore


def write_wav(path: Path | str, pcm_or_wav: bytes, sample_rate: int = 16000) -> Path:
    path = Path(path)
    if pcm_or_wav[:4] == b"RIFF":
        path.write_bytes(pcm_or_wav)
        return path
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_or_wav)
    path.write_bytes(buf.getvalue())
    return path


def play_wav_bytes(data: bytes, *, sample_rate: int | None = None) -> None:
    """Play WAV or raw PCM16 mono. Prefer sounddevice; fall back to ffplay/paplay."""
    pcm, sr = _to_pcm16(data, sample_rate)
    if sd is not None:
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        sd.play(samples, sr)
        sd.wait()
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        p = Path(tmp.name)
    try:
        write_wav(p, data if data[:4] == b"RIFF" else pcm, sr)
        for cmd in (
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(p)],
            ["paplay", str(p)],
            ["aplay", str(p)],
        ):
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                return
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
        raise RuntimeError("no playback backend (sounddevice/ffplay/paplay/aplay)")
    finally:
        p.unlink(missing_ok=True)


def _to_pcm16(data: bytes, sample_rate: int | None) -> tuple[bytes, int]:
    if data[:4] == b"RIFF":
        with wave.open(io.BytesIO(data), "rb") as wf:
            sr = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
            if wf.getnchannels() > 1:
                # take left
                sampwidth = wf.getsampwidth()
                mono = bytearray()
                step = sampwidth * wf.getnchannels()
                for i in range(0, len(frames), step):
                    mono.extend(frames[i : i + sampwidth])
                frames = bytes(mono)
            return frames, sr
    return data, sample_rate or 24000
