import { useSignal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import { api, ApiRequestError } from "../lib/api";
import { deliveries, refresh } from "../lib/data";
import { onEnvelope } from "../lib/stream";

type Phase = "idle" | "recording" | "transcribing" | "review" | "submitted" | "failed";

const canBrowserMic = (): boolean =>
  window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;

/** Mic capture overlay: record (browser or host) → review → safe submit. */
export function DictateOverlay({ onClose }: { onClose: () => void }) {
  const phase = useSignal<Phase>("idle");
  const mode = useSignal<"browser" | "host">(canBrowserMic() ? "browser" : "host");
  const text = useSignal("");
  const partial = useSignal("");
  const error = useSignal<string | null>(null);
  const target = useSignal<string>("prompt"); // "prompt" | event_id
  const level = useSignal(0);

  const recRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef(0);

  useEffect(() => {
    void refresh("deliveries");
    // host-mode progress arrives on the stream
    return onEnvelope((e) => {
      if (e.source !== "serve") return;
      const p = e.payload as { kind?: string; state?: string; text?: string | null; error?: string | null; partial?: boolean };
      if (p.kind !== "serve.dictation" || mode.value !== "host") return;
      if (p.state === "recording" && p.partial && p.text) partial.value = p.text;
      else if (p.state === "done") {
        text.value = p.text ?? "";
        phase.value = "review";
      } else if (p.state === "failed") {
        error.value = p.error ?? "capture failed";
        phase.value = "failed";
      } else if (p.state === "cancelled") {
        phase.value = "idle";
        partial.value = "";
      }
    });
  }, []);

  const cleanupBrowser = () => {
    window.cancelAnimationFrame(rafRef.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    void audioCtxRef.current?.close().catch(() => {});
    streamRef.current = null;
    audioCtxRef.current = null;
    recRef.current = null;
    level.value = 0;
  };

  useEffect(() => () => cleanupBrowser(), []);

  const startBrowser = async () => {
    error.value = null;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      // VU meter
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const buf = new Uint8Array(analyser.frequencyBinCount);
      const meter = () => {
        analyser.getByteTimeDomainData(buf);
        let peak = 0;
        for (const v of buf) peak = Math.max(peak, Math.abs(v - 128) / 128);
        level.value = peak;
        rafRef.current = window.requestAnimationFrame(meter);
      };
      meter();

      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : undefined;
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      recRef.current = rec;
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.onstop = async () => {
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        cleanupBrowser();
        if (phase.value !== "transcribing") return; // cancelled
        try {
          const res = await api.transcribe(blob);
          text.value = res.text;
          phase.value = res.text ? "review" : "failed";
          if (!res.text) error.value = "empty transcript";
        } catch (err) {
          error.value =
            err instanceof ApiRequestError && err.code === "transcode_unavailable"
              ? "server lacks ffmpeg — browser dictation unavailable (host mic still works)"
              : ((err as Error).message ?? "transcription failed");
          phase.value = "failed";
        }
      };
      rec.start();
      phase.value = "recording";
    } catch (err) {
      error.value = `mic access failed: ${(err as Error).message ?? err}`;
      phase.value = "failed";
    }
  };

  const startHost = async () => {
    error.value = null;
    partial.value = "";
    try {
      await api.dictation("start", { mode: "host" });
      phase.value = "recording";
    } catch (err) {
      error.value =
        err instanceof ApiRequestError && err.code === "mic_busy"
          ? "host mic is busy (ambient/listen holds the lease)"
          : ((err as Error).message ?? "failed to start");
      phase.value = "failed";
    }
  };

  const start = () => (mode.value === "browser" ? startBrowser() : startHost());

  const stop = async () => {
    if (mode.value === "browser") {
      phase.value = "transcribing";
      recRef.current?.stop();
    } else {
      phase.value = "transcribing";
      await api.dictation("stop").catch(() => {});
    }
  };

  const cancel = async () => {
    if (mode.value === "browser") {
      phase.value = "idle";
      recRef.current?.stop();
      cleanupBrowser();
    } else {
      await api.dictation("cancel").catch(() => {});
      phase.value = "idle";
    }
    partial.value = "";
  };

  const submit = async () => {
    if (!text.value.trim()) return;
    try {
      if (target.value === "prompt") {
        await api.prompt(text.value.trim());
        phase.value = "submitted";
      } else {
        const res = await api.answer(target.value, { text: text.value.trim() });
        if (res.status === "delivered" || res.status === "uncertain") {
          phase.value = "submitted";
        } else {
          error.value = `stale target: ${res.detail ?? res.status} — pick a target and retry`;
          phase.value = "failed";
        }
      }
      void refresh("deliveries");
    } catch (err) {
      error.value = (err as Error).message ?? "submit failed";
      phase.value = "failed";
    }
  };

  const pending = deliveries.value?.pending ?? [];

  return (
    <div
      style="position:fixed;inset:0;background:#05070dcc;backdrop-filter:blur(4px);z-index:50;
             display:grid;place-items:center;padding:16px"
      onClick={(e) => e.target === e.currentTarget && phase.value !== "recording" && onClose()}
    >
      <div class="card" style="padding:18px;max-width:560px;width:100%;display:flex;flex-direction:column;gap:12px">
        <div style="display:flex;align-items:center;gap:10px">
          <b>dictate</b>
          <span class="badge">{mode.value} mic</span>
          {canBrowserMic() && phase.value === "idle" && (
            <button
              class="btn small"
              onClick={() => (mode.value = mode.value === "browser" ? "host" : "browser")}
            >
              use {mode.value === "browser" ? "host" : "browser"} mic
            </button>
          )}
          <button class="btn small" style="margin-left:auto" onClick={onClose}>
            ✕
          </button>
        </div>

        <label style="display:flex;gap:8px;align-items:center;font-size:12px">
          <span style="color:var(--text-faint)">deliver to</span>
          <select
            class="input"
            style="flex:1"
            value={target.value}
            onChange={(e) => (target.value = (e.target as HTMLSelectElement).value)}
          >
            <option value="prompt">operator prompt → Mode A judgment (unbound)</option>
            {pending.map((p) => (
              <option key={p.event_id} value={p.event_id}>
                answer {p.session_id}/{p.pane_id} — {(p.question_text ?? "").slice(0, 60)}
              </option>
            ))}
          </select>
        </label>

        {(phase.value === "idle" || phase.value === "failed") && (
          <button class="btn primary" style="justify-content:center;padding:12px" onClick={start}>
            ◉ start recording
          </button>
        )}

        {phase.value === "recording" && (
          <div style="display:flex;flex-direction:column;gap:10px">
            <div style="display:flex;align-items:center;gap:10px">
              <span class="badge err">
                <span class="dot" style="background:var(--error)" /> recording
              </span>
              {mode.value === "browser" && (
                <div style="flex:1;height:8px;border-radius:4px;background:var(--bg-raise);overflow:hidden">
                  <div
                    style={`height:100%;width:${Math.min(100, level.value * 140)}%;background:var(--grad);transition:width 60ms`}
                  />
                </div>
              )}
            </div>
            {partial.value && (
              <div class="qtext" style="color:var(--text-dim)">
                {partial.value}
                <span style="color:var(--text-faint)"> …</span>
              </div>
            )}
            <div style="display:flex;gap:8px">
              <button class="btn primary" style="flex:1;justify-content:center" onClick={stop}>
                ⏹ stop &amp; transcribe
              </button>
              <button class="btn danger" onClick={cancel}>
                cancel
              </button>
            </div>
          </div>
        )}

        {phase.value === "transcribing" && (
          <div class="readout dim" style="justify-content:center;padding:14px">
            ⋯ transcribing
          </div>
        )}

        {(phase.value === "review" || phase.value === "submitted") && (
          <div style="display:flex;flex-direction:column;gap:8px">
            <textarea
              class="input"
              rows={3}
              style="resize:vertical"
              value={text.value}
              disabled={phase.value === "submitted"}
              onInput={(e) => (text.value = (e.target as HTMLTextAreaElement).value)}
            />
            {phase.value === "review" ? (
              <div style="display:flex;gap:8px">
                <button class="btn primary" style="flex:1;justify-content:center" onClick={submit}>
                  ⇧ submit
                </button>
                <button class="btn" onClick={start}>
                  ↺ re-record
                </button>
              </div>
            ) : (
              <div style="color:var(--ok);text-align:center">✓ submitted</div>
            )}
          </div>
        )}

        {error.value && phase.value === "failed" && (
          <div style="color:var(--error);font-size:12px">{error.value}</div>
        )}
        {!window.isSecureContext && (
          <div style="color:var(--text-faint);font-size:11px">
            browser mic needs HTTPS (tailscale serve) — using host mic; see docs/DASHBOARD.md
          </div>
        )}
      </div>
    </div>
  );
}
