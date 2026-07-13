"""Local DSP: capture, gate, playback (no local neural dictation)."""

from hark.audio.capture import MicLease, capture_utterance, record_seconds
from hark.audio.playback import play_wav_bytes, write_wav

__all__ = [
    "MicLease",
    "capture_utterance",
    "record_seconds",
    "play_wav_bytes",
    "write_wav",
]
