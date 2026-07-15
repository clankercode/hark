"""Half-duplex SpeakThenListen orchestration phases (ADR-009).

These are documentation + optional debug labels for the handoff path, not a
public FSM callers drive. Transitions are owned by :mod:`handoff` / :mod:`ask`.
"""

from __future__ import annotations

from enum import Enum


class HandoffState(str, Enum):
    """Phases of TTS → listen → optional confirm.

    * ``speaking`` — TTS play under conference / mute / duck.
    * ``armed`` — near-end signalled (``listen_pre_arm_ms``); sequential path
      may tighten post-TTS guard; overlap path may start capture.
    * ``listening`` — Answer Window open (``bound_answer`` profile).
    * ``confirming`` — readback TTS + silence window (``confirm`` profile).
    """

    SPEAKING = "speaking"
    ARMED = "armed"
    LISTENING = "listening"
    CONFIRMING = "confirming"
