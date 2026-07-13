# Hark Event Protocol (HEP) v1

Normalized events so the orchestrator, Monitor, and future `harkd` share one shape.  
Herdr wire JSON is **external**; HEP is **stable internal**.

## Envelope

Every stdout line from `hark watch` / event bus is one JSON object.

```json
{
  "schema": "hark.event.v1",
  "event_id": "01J…",
  "observed_at": "2026-07-13T14:00:00.000Z",
  "kind": "agent.blocked",
  "priority": 80,
  "session_id": "work",
  "target": {
    "workspace_id": "w1",
    "tab_id": "w1:t1",
    "pane_id": "w1:p6",
    "terminal_id": "term_…",
    "pane_revision": 42,
    "agent": "claude",
    "agent_session": null,
    "friendly_name": "auth reviewer"
  },
  "state": { "from": "working", "to": "blocked", "blocked_epoch": 3 },
  "question": {
    "kind": "permission",
    "text": "Allow running rm -rf build/?",
    "choices": ["Yes", "No"],
    "fingerprint": "blake3:…",
    "confidence": 0.9,
    "risk": "R2"
  },
  "pane_capture": {
    "text": "…recent unwrapped pane body (menu + trailing context)…",
    "line_count": 42,
    "char_count": 1800,
    "truncated": false,
    "source": "recent-unwrapped"
  },
  "disposition": "pending",
  "instructions": "…prefer pane_capture.text; optional hark context work/w1:p6"
}
```

`pane_capture` is attached by default on `agent.blocked`, `agent.needs_input`, and
`agent.question_changed` (config: `[watch] pane_capture`, `pane_capture_lines`,
`pane_capture_max_chars`). Mode A may decide from the embedded body; use
`hark context` only for a live re-read.

Consumers **MUST ignore unknown fields**.

## Kinds

| kind | Meaning |
|------|---------|
| `watch.armed` | Watcher started |
| `watch.heartbeat` | Liveness |
| `watch.error` | Recoverable/fatal watch error |
| `agent.blocked` | Needs human input |
| `agent.question_changed` | Still blocked; ask changed |
| `agent.needs_input` | Status done/idle but pane still shows a menu/ask (false done) — treat like blocked |
| `agent.completed` | Transition to done (judgment required; may pair with needs_input) |
| `agent.state_changed` | Other transitions if `--all-transitions` |
| `target.invalidated` | Pane closed/moved; cancel in-flight |
| `answer.transcribed` | (daemon/library) STT finished |
| `answer.confirmation_required` | R2/R3 or auto-unsure |
| `answer.delivered` | Sent successfully |
| `answer.delivery_uncertain` | Write may have landed; reconcile |
| `answer.rejected` | Stale / policy / user cancel |
| `bridge.degraded` / `bridge.recovered` | Herdr/provider issues |
| `ambient.partial` | **Radio mode only** — interim STT while waiting for end phrase |
| `ambient.prompt` | Final ambient operator prompt (`final=true`) |
| `ambient.cancelled` | Operator cancelled mid-capture |

### Partial streaming (radio end mode)

When `[listen] end_mode = "radio"` and `stream_partials = true`, interim transcripts are emitted after each radio segment (trailing quiet of `radio_partial_silence_s`, default 0.6 s — not a final). HOLD until `final=true` / `ambient.prompt` for the same `stream_id`:

```json
{
  "schema": "hark.event.v1",
  "kind": "ambient.partial",
  "partial": true,
  "final": false,
  "stream_id": "s…",
  "seq": 1,
  "text": "please open the pull request for…",
  "warning": "PARTIAL TRANSCRIPT — not complete. … HOLD …",
  "instructions": "HOLD RESPONSE. … If text clearly ends with a done signal you MUST run agent_control.end_recording …",
  "agent_control": {
    "end_recording": "hark listen-end --stream-id s…",
    "cancel_recording": "hark listen-end --stream-id s… --cancel",
    "hint": "MUST: if the operator clearly finished … run end_recording …"
  }
}
```

The orchestrator **must** finalize a stuck radio capture with `hark listen-end` (finish) when the partial clearly ends with a done signal (`over`, `okay hark send`, `that's all`, `send it`, `stop recording`, `message done`, …) and the stream is still active. Prefer finish over cancel when the thought is complete; use `--cancel` only to abort. Do **not** end mid-clause (`over the weekend`, `send it to staging`). By default (`[listen].soft_end_phrases_enabled = true`), Hark itself also auto-finishes on conservative utterance-final soft closers (`send it`, sentence-final `over`, `okay over`, …) without agent intervention — see [AUDIO_DESIGN.md](AUDIO_DESIGN.md). Set `soft_end_phrases_enabled = false` for product phrases only.

Consumers **MUST**:

1. Treat `partial=true` as **non-authoritative** for full answers / pane delivery.  
2. **Not** speak a full answer to the operator or deliver to a pane based on partials alone.  
3. **May** begin private thinking/planning.  
4. **Must** run `hark listen-end` when a done signal is clear and capture is still active (backup to soft/product end).  
5. On `ambient.prompt` / final with the same `stream_id`: use that text; discard prior partials.

## Monitor profile (`hark watch --for-monitor` / `hark monitor --for-monitor`)

Compact line, no secrets. Agent wake kinds still pass **bounded** `pane_capture`
so orchestrators can answer menus without a mandatory second fetch:

```json
{
  "schema": "hark.event.v1",
  "kind": "agent.blocked",
  "event_id": "01J…",
  "session_id": "work",
  "agent": "claude",
  "name": "auth reviewer",
  "pane_id": "w1:p6",
  "question": "Allow running rm -rf build/?",
  "risk": "R2",
  "pane_capture": {
    "text": "…recent pane body…",
    "char_count": 1800,
    "truncated": false,
    "source": "recent-unwrapped"
  },
  "instructions": "Use the hark skill; do not invent an answer. Pane capture attached (pane_capture.text) — decide from it when sufficient. Optional live re-read: hark context work/w1:p6"
}
```

## Dedupe key

```text
(session_id, pane_id, agent_session?, blocked_epoch, question_fingerprint)
```

Reconnect/replay must not re-speak identical asks.

## Debounce

Status edges: **150–400 ms** coalesce.  
`pane.closed` / disconnect: **not** debounced.

## Bound command (delivery)

```json
{
  "schema": "hark.command.v1",
  "request_id": "…",
  "command": "answer.submit",
  "event_id": "01J…",
  "expected": {
    "session_id": "work",
    "pane_id": "w1:p6",
    "pane_revision": 42,
    "question_fingerprint": "blake3:…"
  },
  "text": "No, keep the build directory.",
  "keys": null
}
```

Or menu delivery: `"keys": ["2", "enter"]`.

CLI: `hark answer <event_id> --text "…" | --keys 2 enter`

Rejects if expectation fails (safer than free `hark reply` for production loops).

## JSON Schema

Normative file: `schemas/event-v1.schema.json` (in repo).  
Interaction FSM states (for `harkd` / queue): see prior art interaction schema — optional in handsfree.
