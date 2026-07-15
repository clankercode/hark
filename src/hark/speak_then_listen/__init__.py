"""Deep SpeakThenListen module: TTS → arm → listen → optional confirm.

Half-duplex handoff (ADR-009) and confirm turns live here. Answer Window is
listen-only — this package calls ``run_listen`` / profiles. See
``docs/plans/P1-M4-speak-then-listen.md``.
"""

from __future__ import annotations

from hark.speak_then_listen.ask import run_ask
from hark.speak_then_listen.handoff import attach_tts_info, speak_and_listen
from hark.speak_then_listen.states import HandoffState

__all__ = [
    "HandoffState",
    "attach_tts_info",
    "run_ask",
    "speak_and_listen",
]
