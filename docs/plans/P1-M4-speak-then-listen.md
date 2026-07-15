# P1.M4 — Deepen Speak-then-Listen Handoff

**Status:** design locked for E1 (implementation follows E2–E4)  
**Date:** 2026-07-15  
**Backlog:** `P1.M4` · architecture review candidate 4 (Worth exploring)  
**ADRs in force:** 009 (half-duplex / no barge-in), 008 (event-driven answer windows)  
**Depends on:** P1.M1 Answer Window (done — `open(policy) → ListenResult`)

## Goal

Collapse TTS→listen handoff and confirm turns into one **deep** SpeakThenListen module:

- **Small external interface** — callers use `speak_and_listen` / `run_ask` (or a single handoff entry) without owning thread state, discard windows, or mute/duck ordering.
- **Large implementation** — half-duplex vs overlap pre-arm, near-end arm, `audio_ok_after` discard ownership, confirm readback + silence listen + lexicon.
- **Answer Window is listen-only** — this module **calls** `run_listen` / `open_answer_window` with profiles; it does not re-implement radio/silence sessions.

## Problem (current)

Half-duplex handoff (ADR-009) lives as nested thread state in `speech.speak_and_listen`:

| Surface today | Internal complexity |
|---------------|---------------------|
| `speak_and_listen` thread + `handoff["tts_done_at"]` | Overlap pre-arm vs sequential half-duplex |
| `run_tts` conference → mute → duck nesting | Call order must not be re-invented at call sites |
| `run_ask` confirm path | Readback TTS + `profile="confirm"` silence listen + lexicon — same half-duplex world |
| CLI `cmd_tts --listen` / `cmd_ask` | Thin callers that must not own discard windows |

Mute/duck/conference adapters (`mic_mute`, `media.duck_media`, `conference`) are correct as **adapters**; ownership of *when* they run relative to listen arm should sit in one module.

## Solution

```text
                    ┌──────────────────────────────────────────┐
  call sites  ──►   │  SpeakThenListen                          │
  (thin facades)    │  speak_and_listen / run_ask               │
                    ├──────────────────────────────────────────┤
                    │  states: speaking → armed → listening     │
                    │           → (optional) confirming         │
                    │  owns: near-end arm, overlap discard,     │
                    │        tts_info error attachment          │
                    │  calls: run_tts · run_listen (Answer Win) │
                    │         confirm_lexicon                   │
                    └──────────────────────────────────────────┘
```

Package path: `src/hark/speak_then_listen/` (mirrors `answer_window/`).

---

## External interface

### Primary entries (stable public names)

```python
def speak_and_listen(
    cfg: HarkConfig,
    text: str,
    *,
    provider: str | None = None,
    voice: str | None = None,
    end_mode: str | None = None,
    out: Path | None = None,
    mute_mic: bool | None = None,
    on_partial: Any | None = None,
    partial_kind: str = "ambient.partial",
) -> tuple[dict[str, Any], ListenResult]:
    """TTS then listen: half-duplex default or optional overlap pre-arm."""

def run_ask(
    cfg: HarkConfig,
    prompt: str,
    *,
    confirm: str | None = None,
    end_mode: str | None = None,
    provider: str | None = None,
    risk_hint: str | None = None,
) -> dict[str, Any]:
    """Speak prompt, listen, optional confirm profile turn. JSON-shaped result."""
```

`speech.py` becomes a **thin re-export** of these symbols (import path `hark.speech.speak_and_listen` stays valid for CLI/tests).

### Half-duplex states

| State | Meaning | Transitions |
|-------|---------|-------------|
| `speaking` | TTS play under mute/duck/conference hold | → `armed` on near-end (if `listen_pre_arm_ms > 0`); → `listening` after TTS ends (half-duplex) |
| `armed` | Near-end signalled; sequential path may skip/tighten post-TTS guard | → `listening` (overlap starts capture thread here; half-duplex waits for TTS end) |
| `listening` | Answer Window open (`bound_answer` profile) | → done, or → `confirming` from `run_ask` when risk requires |
| `confirming` | Readback TTS + silence Answer Window (`confirm` profile) + lexicon | → done (yes / cancel / timeout) |

States are **orchestration phases** (documented + optional debug field); not a public FSM API callers must drive.

### Error modes and `tts_info` attachment

| Mode | Behavior (preserve) |
|------|---------------------|
| Listen `TimeoutError` / `ProviderError` after TTS | Exception carries `exc.tts_info` when TTS already ran; `run_ask` maps to `{ok: false, tts: …, exit: …}` |
| TTS conference skip | `tts_info.skipped` / reason; listen still proceeds only if speak path returned (current behavior) |
| Listen cancel / meta-command | `run_ask` returns cancelled / meta_command without confirm |
| Confirm timeout | `{ok: false, error: "confirm timeout", text: listened.text, tts: tts_info}` |
| Confirm not-yes | `{ok: false, cancelled: true, confirm_reply, text, tts}` |
| Success | `{ok: true, text, provider, duration_ms, end_mode, end_phrase, risk, tts, exit: OK}` |

**Invariant:** JSON fields returned by `run_ask` / CLI ask / `tts --listen` **must not change** shape (E3.T002).

### TTS play stack order (internalized)

Owned by `run_tts` (stays in `speech.py` as the synth/play engine); SpeakThenListen **calls** it and must not re-order:

1. **Conference hold** (`apply_conference_hold`) — before synth exclusive play  
2. **Mic mute** (`mic_muted_during_tts`) — around exclusive playback  
3. **Media duck** (`duck_media`, `exclude_conference=True`) — nested inside mute  

Adapters remain in `conference.py`, `audio/mic_mute.py`, `audio/media.py`. Module docs + tests assert order, not reimplementation.

### Overlap pre-arm + discard (ADR-009)

| Mode | Config | Behavior |
|------|--------|----------|
| Half-duplex (default) | `overlap_prearm=false` | Capture starts **after** TTS exits mute; near-end only sets `armed` for guard tightening |
| Overlap pre-arm | `overlap_prearm=true` + `listen_pre_arm_ms > 0` | Capture thread starts at near-end; frames discarded until `tts_done_at + overlap_discard_ms` via `audio_ok_after` |

**No barge-in:** operator speech during TTS is not transcribed as answer content until discard window closes. Echo rejection (`last_tts`) remains Answer Window concern.

---

## Dependency on M1 Answer Window (E1.T002)

| Question | Decision |
|----------|----------|
| Temporary facade vs real M1? | **Real M1** — `P1.M1.E4.T003` is done. Listen path is `run_listen` → `policy_from_config` + `open_answer_window`. |
| Does SpeakThenListen open the window directly? | Prefer **`run_listen` facade** with `profile=` so gate knobs stay in one place. Direct `open_answer_window` only if a handoff-only override cannot express via facade. |
| Confirm path | `run_listen(..., profile="confirm", end_mode="silence", last_tts=readback)` |
| Bound answer after TTS | `run_listen(..., profile="bound_answer", already_armed=…, post_tts_guard_s=…, audio_ok_after=…)` |
| Ordering vs M1 | **Prefer after M1** (satisfied). Do not re-shard radio/silence into this module. |
| Ordering vs M3 pane understanding | **Orthogonal** — no shared files expected; peer agent may touch `watch.py` / events. Avoid non-handoff edits in `speech.py` beyond re-exports. |

### Ordering notes (plan)

1. E1 design (this doc) — states, errors, tts_info, M1 dep.  
2. E2 extract handoff module + re-export + mute/duck/conference order tests + overlap ownership.  
3. E3 confirm as same module + wire CLI.  
4. E4 port/green handoff tests + ARCHITECTURE locality.

---

## Module layout

```text
src/hark/speak_then_listen/
  __init__.py      # re-export public API
  states.py        # HandoffState enum + helpers
  handoff.py       # speak_and_listen + discard / arm
  ask.py           # run_ask + confirm profile
```

| Stays in `speech.py` | Moves to `speak_then_listen` |
|----------------------|------------------------------|
| `run_tts`, chunking, question print helpers | `speak_and_listen` |
| `run_listen` thin Answer Window facade | `run_ask` |
| Re-exports of ListenResult / empty-stt constants | State docs / optional phase enum |

---

## Facades and call sites

| Call site | After |
|-----------|--------|
| `speech.speak_and_listen` / `run_ask` | Re-export from package |
| `cli.cmd_tts --listen` | Unchanged imports from `hark.speech` |
| `cli.cmd_ask` | Unchanged |
| Tests monkeypatching `hark.speech.run_tts` / `run_listen` | Late-bound imports inside handoff so patches still apply |

---

## Invariants

1. **ADR-009:** no barge-in; half-duplex default; optional overlap discards TTS tail.  
2. **Answer Window is listen-only** — handoff owns transitions into it.  
3. **Confirm R2/R3 path intact** — readback + silence + lexicon.  
4. **JSON / CLI exit codes stable** for ask and tts --listen.  
5. **Mute/duck/conference adapters stay**; call order owned by TTS play stack.  
6. **Library must not** apply LLM judgment to confirm text (lexicon only).

## Non-goals (M4)

1. No Answer Window radio/silence rewrite.  
2. No STT/TTS provider rewrite; no HEP schema bump.  
3. No Mode B dialogue FSM.  
4. No moving `run_tts` synth/chunk pipeline (only handoff ownership).  
5. No barge-in / full-duplex product mode.

## Acceptance criteria (milestone)

| # | Criterion | How we know |
|---|-----------|-------------|
| AC1 | Deep module owns speak→listen (+ confirm) | Package exists; speech re-exports thin |
| AC2 | Half-duplex states documented | Plan + ARCHITECTURE |
| AC3 | Error modes + tts_info attachment specified and preserved | Plan + run_ask tests |
| AC4 | Mute/duck/conference order internalized (adapters stay) | Tests / docs |
| AC5 | Overlap prearm + discard owned by module | Overlap tests green |
| AC6 | Confirm profile path intact (R2/R3) | Confirm/ask tests |
| AC7 | CLI wire JSON fields unchanged | cmd_ask / tts --listen |
| AC8 | Handoff/overlap/arm-cue tests green; ARCHITECTURE updated | CI + docs |

## Residual risks

| Risk | Mitigation |
|------|------------|
| Monkeypatch path break | Late-import `run_tts`/`run_listen` from `hark.speech` inside handoff |
| Overlap race regressions | Keep existing `test_tts_listen_flag` ordering tests |
| Peer M3 conflict on `speech.py` | Only move handoff/ask + re-export; leave rest |

## Implementation order

1. **E1** — this plan (T001 interface/states/errors; T002 M1 dependency notes).  
2. **E2.T001** — move `speak_and_listen`; thin re-export.  
3. **E2.T002** — document/test conference→mute→duck order via call stack.  
4. **E2.T003** — ensure discard window ownership lives only in module.  
5. **E3** — `run_ask` + confirm in module; CLI still via speech.  
6. **E4** — tests green + ARCHITECTURE + CHANGELOG.
