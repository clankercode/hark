# Session note — Python prototype ready for testing

**Date:** 2026-07-13  
**Canonical path:** `/home/xertrov/src/grok/hark`

## Dogfooding rule

Any problem while operating Hark is a chance to improve it. Always:

1. Add a **todo** for the issue in the agent session list.  
2. File a durable **`bl bug`** when it should outlive the session.  
3. Fix immediately if small; otherwise continue current work and return later.

Skill text: `skill/hark/SKILL.md` § Dogfooding.

## Status

Phase 1 Python prototype is implemented enough for operator testing:

- Herdr: doctor, status, context, watch (poll + socket auto), reply/keys
- Speech: tts / listen / ask (xAI OAuth primary; OpenAI/Google/MiniMax)
- Radio end phrases (product-scoped defaults)
- Ambient wake config + local snippet scanner (vosk optional)
- Bound `answer` delivery store with stale/fingerprint checks
- SSH tunnel helper for remote sessions

## Try

```bash
cd /home/xertrov/src/grok/hark
uv sync
uv run hark doctor
uv run hark tts "Hark is ready for testing."
uv run hark listen
uv run pytest
```

## Config

`uv run hark config init` → `~/.config/hark/config.toml`

## Not v1

- `harkd` Mode B daemon
- Perfect production AEC / barge-in
- Ambient without installing a vosk model (engine=vosk needs model_path)
