# Session note — save check

**Date:** 2026-07-13  
**Canonical path:** `/home/xertrov/src/grok/hark`  
**Stale path (deleted):** `/home/xertrov/src/grok/handsfree-agents`  

## Status

All plan/spec/skill work for Hark was written **into this tree** (via absolute paths) after the rename. Nothing material remains only on the deleted `handsfree-agents` cwd.

If your editor/agent session still claims cwd is `handsfree-agents`, **reopen** `/home/xertrov/src/grok/hark`. Shell tools fail until the workspace root exists again.

## Inventory (on disk here)

```
README.md
SESSION_NOTE.md          # this file
docs/
  ACCEPTANCE.md
  ARCHITECTURE.md
  AUDIO_DESIGN.md
  BRANDING_SOURCE.md
  DECISIONS.md
  EXAMPLE_SESSION.md
  HERDR.md
  IMPLEMENTATION.md
  NAMING.md
  OPEN_QUESTIONS.md
  PRIOR_ART.md
  PRODUCT.md
  PROTOCOL.md
  PROVIDERS.md
  SAFETY.md
  SPEC.md
prototype/
  herdr_event_monitor.py
schemas/
  event-v1.schema.json
scripts/
  capture-herdr-schema.sh
skill/
  SKILL.md               # shim
  hark/SKILL.md          # primary skill name: hark
  handsfree/SKILL.md     # alias skill name: handsfree
```

## Locked decisions (also in docs/OPEN_QUESTIONS.md)

- Product/CLI: **hark**
- Skill: **hark** + alias **handsfree**
- Mode A only for v1 (no harkd yet)
- Multi-session Herdr, local orchestrator outside Herdr
- Confirm auto R0/R1; always R2/R3
- xAI via Grok Build OAuth preferred

## Progress (2026-07-13 resume)

- Checkpoint commit: Phase 0 docs/skills/prototype
- Phase 1 started: `src/hark` package via `uv`
  - `hark doctor`, `config`, `status`, `watch --for-monitor`, `context`
  - `reply` / `keys` best-effort; `answer` bound store still TODO
  - speech (`tts`/`listen`/`ask`) not yet

## Next

```bash
cd /home/xertrov/src/grok/hark
uv sync
uv run hark doctor
# then: tts/listen via xAI OAuth, bound answer store, socket subscribe
```
