#!/usr/bin/env bash
# Run Hark handsfree properly: Herdr watch + ambient wake (hey hark).
# Preferred CLI equivalent: `hark start` / `hark stop` / `hark restart`.
#
#   ./scripts/run-mode-a.sh
#   ./scripts/run-mode-a.sh --no-ambient
#   ./scripts/run-mode-a.sh --stop          # graceful: wait for active recording
#   ./scripts/run-mode-a.sh --stop --force  # SIGKILL if still up after grace
#
# Logs:
#   ~/.local/state/hark/watch.jsonl
#   ~/.local/state/hark/ambient.jsonl
#   ~/.local/state/hark/system.jsonl
# PIDs:
#   ~/.local/state/hark/mode-a.pids
# Refuses start if experimental harkd is live (~/.local/state/hark/harkd.pid).
# Busy marker (while user is recording):
#   ~/.local/state/hark/busy.lock
#
# Single-instance: before start, previous workers (pidfile + orphans)
# are stopped; the pidfile is always rewritten from scratch with only live PIDs.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/hark"
mkdir -p "$STATE"
PIDFILE="$STATE/mode-a.pids"
HARKD_PIDFILE="$STATE/harkd.pid"
BUSY="$STATE/busy.lock"
WATCH_LOG="$STATE/watch.jsonl"
AMBIENT_LOG="$STATE/ambient.jsonl"
SYSTEM_LOG="$STATE/system.jsonl"

DO_WATCH=1
DO_AMBIENT=1
FORCE=0
SESSION="${HARK_SESSION:-default}"
# Max wait for an in-flight recording (seconds)
STOP_GRACE="${HARK_STOP_GRACE_S:-120}"

# reason: stop | restart — written so ambient can TTS the right line
stage_shutdown_reason() {
  local reason="${1:-stop}"
  echo "$reason" >"$STATE/shutdown_reason"
  export HARK_SHUTDOWN_REASON="$reason"
}

# Python owns the structured process identity format and pidfd-safe signalling.
# Keeping the shell as an adapter prevents its stop path from drifting from
# `hark stop` while preserving orphan discovery.
worker_identity() {
  (cd "$ROOT" && uv run python -m hark.worker_process "$@")
}

# Unique identity-verified workers from the pidfile plus /proc orphan scan.
collect_mode_a_pids() {
  worker_identity collect "$PIDFILE" --discover
}

# Capture producer status explicitly. Bash process substitution reports only
# mapfile's status, which could otherwise turn an identity-tool failure into an
# empty successful collection.
collect_mode_a_pids_into() {
  local destination="$1"
  local output
  local -a parsed=()
  output="$(collect_mode_a_pids)" || return $?
  if [[ -n "$output" ]]; then
    mapfile -t parsed <<<"$output"
  fi
  local -n result="$destination"
  result=("${parsed[@]}")
}

# Emergency durable ownership when post-spawn identity discovery itself fails.
# Bare PIDs are the legacy format and will be migrated only after argv validation.
write_legacy_pidfile() {
  (($# > 0)) || return 1
  local temporary="${PIDFILE}.$$.tmp"
  printf '%s\n' "$@" >"$temporary"
  mv -f "$temporary" "$PIDFILE"
}

signal_pids() {
  local sig="$1"
  worker_identity signal "$PIDFILE" "$sig" --discover >/dev/null
}

graceful_stop() {
  local force="$1"
  local reason="${2:-stop}"
  stage_shutdown_reason "$reason"

  local -a pids=()
  if ! collect_mode_a_pids_into pids; then
    echo "error: failed to collect Hark worker identities; refusing to stop" >&2
    return 1
  fi

  if ((${#pids[@]} == 0)); then
    echo "no Hark workers running"
    rm -f "$PIDFILE"
    return 0
  fi

  echo "sending SIGTERM (graceful, reason=$reason) to: ${pids[*]}"
  if ! signal_pids TERM "${pids[@]}"; then
    echo "error: failed to signal verified Hark workers; retaining pidfile" >&2
    return 1
  fi

  # If recording, wait until busy.lock clears (or processes exit).
  # Re-scan each tick so orphaned python children of a dead uv parent are tracked.
  local waited=0
  local -a still=()
  while [[ $waited -lt $STOP_GRACE ]]; do
    if ! collect_mode_a_pids_into still; then
      echo "error: failed to refresh Hark worker identities; retaining pidfile" >&2
      return 1
    fi

    if ((${#still[@]} == 0)); then
      echo "all Hark workers exited cleanly (${waited}s)"
      rm -f "$PIDFILE" "$BUSY"
      return 0
    fi

    if [[ -f "$BUSY" ]] && [[ $((waited % 5)) -eq 0 ]]; then
      echo "waiting for active recording to finish… (${waited}s / ${STOP_GRACE}s)"
      cat "$BUSY" 2>/dev/null || true
    fi
    sleep 1
    waited=$((waited + 1))
  done

  if ! collect_mode_a_pids_into still; then
    echo "error: failed to refresh Hark worker identities; retaining pidfile" >&2
    return 1
  fi

  if [[ "$force" -eq 1 ]]; then
    if ((${#still[@]} > 0)); then
      echo "force-killing remaining processes: ${still[*]}"
      if ! signal_pids KILL "${still[@]}"; then
        echo "error: failed to signal verified Hark workers; retaining pidfile" >&2
        return 1
      fi
    else
      echo "force-killing remaining processes: none"
    fi
    rm -f "$PIDFILE" "$BUSY"
    return 0
  fi

  echo "warning: still running after ${STOP_GRACE}s; use --force to SIGKILL" >&2
  return 1
}

# Test/support hook: load the adapters without executing lifecycle actions.
if [[ "${HARK_RUN_MODE_A_SOURCE_ONLY:-0}" -eq 1 ]]; then
  return 0 2>/dev/null || exit 0
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-watch) DO_WATCH=0; shift ;;
    --no-ambient) DO_AMBIENT=0; shift ;;
    --session) SESSION="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --stop)
      shift
      # allow --stop --force
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --force) FORCE=1; shift ;;
          *) break ;;
        esac
      done
      graceful_stop "$FORCE" "stop"
      exit $?
      ;;
    -h | --help)
      sed -n '2,20p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "unknown: $1" >&2; exit 1 ;;
  esac
done

# Refuse to race experimental harkd (docs/HARKD.md): single always-on owner.
if [[ -f "$HARKD_PIDFILE" ]]; then
  harkd_pid="$(tr -d '[:space:]' <"$HARKD_PIDFILE" 2>/dev/null || true)"
  if [[ "$harkd_pid" =~ ^[0-9]+$ ]] && kill -0 "$harkd_pid" 2>/dev/null; then
    echo "error: harkd is running (pid $harkd_pid via $HARKD_PIDFILE)" >&2
    echo "  stop it first: uv run hark daemon stop" >&2
    echo "  (handsfree workers and harkd must not both own ambient/watch — see docs/HARKD.md)" >&2
    exit 1
  fi
  # stale pidfile
  rm -f "$HARKD_PIDFILE"
fi

cd "$ROOT"

# Sherpa-ONNX needs libonnxruntime.so from the onnxruntime wheel (capi/).
# Inject into LD_LIBRARY_PATH so ambient can import sherpa_onnx.
_ort_capi="$(
  cd "$ROOT" && uv run python -c '
from pathlib import Path
try:
    import onnxruntime
    print(Path(onnxruntime.__file__).resolve().parent / "capi")
except Exception:
    pass
' 2>/dev/null || true
)"
if [[ -n "$_ort_capi" && -d "$_ort_capi" ]]; then
  export LD_LIBRARY_PATH="${_ort_capi}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

HARK=(uv run hark)

# Always replace previous workers (pidfile and/or orphan ambient/watch)
# so partial restarts cannot leave duplicate ambients.
_prev=()
if ! collect_mode_a_pids_into _prev; then
  echo "error: failed to collect existing Hark worker identities; refusing to start" >&2
  exit 1
fi
prev_count=${#_prev[@]}

if [[ $prev_count -gt 0 ]]; then
  echo "restarting previous workers (graceful, ${#_prev[@]} pid(s))…"
  graceful_stop 0 "restart" || graceful_stop 1 "restart"
  # Allow ambient to finish shutdown TTS after recording
  sleep 0.5
fi

# Fresh pidfile: only live processes from this start will be recorded
rm -f "$PIDFILE"

started=()

if [[ "$DO_WATCH" -eq 1 ]]; then
  echo "starting watch → $WATCH_LOG (session=$SESSION)"
  nohup "${HARK[@]}" watch --session "$SESSION" --for-monitor --statuses blocked,done \
    >>"$WATCH_LOG" 2>&1 &
  started+=("$!")
fi

if [[ "$DO_AMBIENT" -eq 1 ]]; then
  echo "starting ambient loop → $AMBIENT_LOG"
  # List configured wake/trigger phrases (custom via config [ambient])
  PHRASE_LINE="$(
    cd "$ROOT" && python3 -c '
from hark.config import load_config
ps = load_config().ambient.activation_phrases
print("  say: " + " / ".join(ps[:10]) + (" …" if len(ps) > 10 else ""))
' 2>/dev/null || echo "  say: hey hark / hey herald (or custom trigger_phrases)"
  )"
  echo "$PHRASE_LINE"
  nohup "${HARK[@]}" ambient \
    >>"$AMBIENT_LOG" 2>&1 &
  started+=("$!")
fi

sleep 1

# Prefer full discovery (uv + python children) so the pidfile is complete;
# fall back to $! list if scan is empty (race before exec).
live=()
if ! collect_mode_a_pids_into live; then
  echo "error: failed to discover started Hark workers; retaining legacy ownership" >&2
  if ((${#started[@]} > 0)); then
    write_legacy_pidfile "${started[@]}" || true
  fi
  exit 1
fi
if ((${#live[@]} > 0)); then
  : # collect_mode_a_pids already wrote canonical structured identities
elif ((${#started[@]} > 0)); then
  write_legacy_pidfile "${started[@]}"
  live=("${started[@]}")
else
  rm -f "$PIDFILE"
fi

if [[ -f "$PIDFILE" ]]; then
  echo "PIDs: ${live[*]}"
else
  echo "PIDs: (none — nothing started or already exited)"
fi
echo "tail logs:"
echo "  uv run hark logs -f"
echo "  tail -f $SYSTEM_LOG"
echo "  tail -f $AMBIENT_LOG"
echo "stop:  $0 --stop          # waits for recording to finish"
echo "       $0 --stop --force  # hard kill after grace"
if [[ -f "$AMBIENT_LOG" ]]; then
  echo "--- ambient (recent) ---"
  tail -n 3 "$AMBIENT_LOG" 2>/dev/null || true
fi
