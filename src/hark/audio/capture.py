"""Microphone capture with adaptive energy gate and single-mic lease."""

from __future__ import annotations

import io
import struct
import threading
import time
import wave
from dataclasses import dataclass
from typing import Callable

import numpy as np

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover
    sd = None  # type: ignore


class MicBusyError(RuntimeError):
    pass


class MicLease:
    """Process-wide single mic lease."""

    _lock = threading.Lock()
    _holder: str | None = None

    def __init__(self, name: str = "hark") -> None:
        self.name = name
        self._held = False

    def __enter__(self) -> MicLease:
        with MicLease._lock:
            if MicLease._holder is not None:
                raise MicBusyError(f"mic busy ({MicLease._holder})")
            MicLease._holder = self.name
            self._held = True
        return self

    def __exit__(self, *args: object) -> None:
        with MicLease._lock:
            if self._held and MicLease._holder == self.name:
                MicLease._holder = None
            self._held = False


def _require_sd() -> None:
    if sd is None:
        raise RuntimeError(
            "sounddevice not installed — run: uv sync  (needs PortAudio)"
        )


def pcm16_mono_bytes(samples: np.ndarray) -> bytes:
    samples = np.clip(samples, -1.0, 1.0)
    ints = (samples * 32767.0).astype(np.int16)
    return ints.tobytes()


def write_wav_bytes(pcm16: bytes, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16)
    return buf.getvalue()


def record_seconds(
    seconds: float,
    *,
    sample_rate: int = 16000,
    device: int | str | None = None,
) -> bytes:
    """Record fixed duration mono float→PCM16."""
    _require_sd()
    frames = int(seconds * sample_rate)
    audio = sd.rec(
        frames,
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=device,
    )
    sd.wait()
    return pcm16_mono_bytes(audio.reshape(-1))


@dataclass
class CaptureResult:
    pcm16: bytes
    sample_rate: int
    duration_ms: int
    speech_ms: int

    @property
    def wav(self) -> bytes:
        return write_wav_bytes(self.pcm16, self.sample_rate)


def capture_utterance(
    *,
    sample_rate: int = 16000,
    max_s: float = 120.0,
    end_silence_s: float = 1.1,
    min_speech_s: float = 0.3,
    open_margin_db: float = 12.0,
    initial_timeout_s: float = 30.0,
    device: int | str | None = None,
    should_stop: Callable[[bytes, float], bool] | None = None,
    post_tts_guard_s: float = 0.0,
) -> CaptureResult:
    """Energy-gated capture until end silence or should_stop or max.

    should_stop(pcm_so_far, elapsed_s) → True to end (e.g. radio phrase after STT
    is handled by outer loop; here used for max/external cancel).
    """
    _require_sd()
    if post_tts_guard_s > 0:
        time.sleep(post_tts_guard_s)

    block = int(sample_rate * 0.02)  # 20 ms
    noise_floor = 1e-4
    open_thresh = None
    opened = False
    speech_blocks = 0
    silent_blocks = 0
    end_silence_blocks = max(1, int(end_silence_s / 0.02))
    min_speech_blocks = max(1, int(min_speech_s / 0.02))
    max_blocks = int(max_s / 0.02)
    timeout_blocks = int(initial_timeout_s / 0.02)

    chunks: list[np.ndarray] = []
    start = time.monotonic()

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=block,
        device=device,
    ) as stream:
        for i in range(max_blocks):
            data, overflowed = stream.read(block)
            del overflowed
            samples = data.reshape(-1)
            rms = float(np.sqrt(np.mean(samples**2)) + 1e-12)
            db = 20.0 * np.log10(rms)

            if not opened:
                # adapt noise floor while closed
                noise_floor = 0.95 * noise_floor + 0.05 * rms
                open_thresh = 20.0 * np.log10(noise_floor + 1e-12) + open_margin_db
                if db >= open_thresh:
                    speech_blocks += 1
                    if speech_blocks >= 8:  # ~160 ms confirm
                        opened = True
                        silent_blocks = 0
                else:
                    speech_blocks = max(0, speech_blocks - 1)
                if i >= timeout_blocks and not opened:
                    raise TimeoutError("no speech detected")
            else:
                chunks.append(samples.copy())
                if open_thresh is not None and db >= open_thresh - 3:
                    silent_blocks = 0
                    speech_blocks += 1
                else:
                    silent_blocks += 1
                    if (
                        silent_blocks >= end_silence_blocks
                        and speech_blocks >= min_speech_blocks
                    ):
                        break

            if should_stop is not None:
                pcm = pcm16_mono_bytes(np.concatenate(chunks)) if chunks else b""
                if should_stop(pcm, time.monotonic() - start):
                    break

    if not chunks:
        raise TimeoutError("no speech captured")

    all_s = np.concatenate(chunks)
    pcm = pcm16_mono_bytes(all_s)
    dur_ms = int(1000 * len(all_s) / sample_rate)
    speech_ms = int(1000 * speech_blocks * 0.02)
    return CaptureResult(
        pcm16=pcm, sample_rate=sample_rate, duration_ms=dur_ms, speech_ms=speech_ms
    )


def list_input_devices() -> list[dict]:
    _require_sd()
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) > 0:
            out.append(
                {
                    "id": i,
                    "name": d.get("name"),
                    "channels": d.get("max_input_channels"),
                    "default_sr": d.get("default_samplerate"),
                }
            )
    return out
