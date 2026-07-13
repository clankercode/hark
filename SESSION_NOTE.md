# Session note — Python prototype ready for testing

**Date:** 2026-07-13  
**Canonical path:** `/home/xertrov/src/grok/hark`

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
