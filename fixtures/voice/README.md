# Voice fixtures (for automated wake / STT tests)

Drop short WAV clips of the operator’s voice here so we can regression-test
ambient wake and cloud STT without a live mic session.

## Layout

```text
fixtures/voice/
  README.md                 # this file
  wake/
    hey-hark-clean.wav      # clear “hey hark”
    hey-hark-bg-noise.wav   # same with room/keyboard noise
    hey-herald-clean.wav
    hey-herald-bg-noise.wav
    hey-hook-mishear.wav    # optional: natural phrasing vosk might garble
    negative-no-wake.wav    # ordinary speech, must NOT wake
  stt/
    short-prompt-clean.wav  # e.g. “open the PR checklist”
    short-prompt-bg.wav
```

## Recording guide (Elgato Wave)

Prefer **16 kHz mono PCM WAV** (what ambient/vosk uses):

```bash
# example with ffmpeg + default pulse source (Wave if default)
ffmpeg -f pulse -i default -ac 1 -ar 16000 -t 3 \
  fixtures/voice/wake/hey-hark-clean.wav
```

Or record in any tool and convert:

```bash
ffmpeg -i ~/Recording.wav -ac 1 -ar 16000 fixtures/voice/wake/hey-hark-bg-noise.wav
```

### Tips

| Clip | Content | Length |
|------|---------|--------|
| clean wake | just “hey hark” or “hey herald” | 1–2 s |
| bg-noise wake | same + keyboard/room noise | 2–3 s |
| negative | “what about the hard drive” (no hey) | 2–3 s |
| stt prompt | full short command after wake | 2–5 s |

Speak at normal distance from the Wave. One utterance per file.

## Using fixtures in tests (later)

```python
pcm = Path("fixtures/voice/wake/hey-hark-clean.wav").read_bytes()
# convert wav→pcm16 if needed, then:
hit = backend.score_snippet(pcm16, 16000)
assert hit and "hark" in hit.phrase
```

When you have files ready, drop them under `fixtures/voice/` and say the word —
we’ll wire automated tests against them.
