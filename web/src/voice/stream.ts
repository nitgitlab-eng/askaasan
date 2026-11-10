/**
 * Live conversation listening: the mic is streamed, continuously, as 16 kHz PCM16 mono over `ws/voice-stream/` to
 * Aasan's server, which streams it on to Deepgram and sends back transcript events. The Deepgram key stays server-side.
 *
 * The mic and the socket stay open the whole time, including while Aasan speaks: echo cancellation in getUserMedia
 * plus the echo check in `bargeIn.ts` keep Aasan's own voice from being taken as the learner's.
 */
import { ensureFreshAccess } from "@/lib/api";
import { useAuth } from "@/stores/auth";

import type { Lang } from "./engines";

export type StreamEvent =
  | { type: "ready" }
  | { type: "started" }
  | { type: "speech_started" }
  | { type: "interim"; text: string }
  | { type: "final"; text: string; speech_final: boolean }
  | { type: "utterance_end" }
  | { type: "error"; code: string };

export interface VoiceStream {
  /** Mic loudness 0..1 (for the live indicator). */
  level(): number;
  stop(): void;
}

export const TARGET_RATE = 16000;
/** ~100 ms of audio per frame. */
export const FRAME_SAMPLES = 1600;

/** Errors that end live listening for good (no reconnect): show them and switch off. */
export const FATAL_STREAM_ERRORS = new Set([
  "unauthorized", "feature_off", "guardian_consent_required", "plan_limit", "voice_budget_exceeded", "streaming_unavailable", "invalid_key", "rate_limited", "bad_audio",
]);

/** Turns any-rate Float32 mic audio into 16 kHz PCM16 frames of FRAME_SAMPLES (box-filter downsampling, stateful
 * across calls so no samples are lost at chunk edges). */
export class Downsampler {
  private ratio: number;
  private pos = 0; // fractional read position into the carried-over input
  private carry = new Float32Array(0);
  private out: number[] = [];

  constructor(inRate: number) {
    this.ratio = inRate / TARGET_RATE;
  }

  /** Feed mic samples; returns any complete frames. */
  push(input: Float32Array): Int16Array<ArrayBuffer>[] {
    const buf = new Float32Array(this.carry.length + input.length);
    buf.set(this.carry);
    buf.set(input, this.carry.length);
    let pos = this.pos;
    while (pos + this.ratio <= buf.length) {
      const a = Math.floor(pos);
      const b = Math.min(buf.length, Math.floor(pos + this.ratio));
      let sum = 0;
      for (let i = a; i < Math.max(b, a + 1); i++) sum += buf[i];
      const v = sum / Math.max(1, b - a);
      this.out.push(Math.max(-1, Math.min(1, v)));
      pos += this.ratio;
    }
    const keep = Math.floor(pos);
    this.carry = buf.slice(keep);
    this.pos = pos - keep;
    const frames: Int16Array<ArrayBuffer>[] = [];
    while (this.out.length >= FRAME_SAMPLES) {
      const chunk = this.out.splice(0, FRAME_SAMPLES);
      frames.push(Int16Array.from(chunk, (s) => (s < 0 ? s * 0x8000 : s * 0x7fff)));
    }
    return frames;
  }
}

// The worklet only batches raw samples (~2048) and posts them; downsampling happens on the main thread.
const WORKLET = `
class AasanCapture extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(2048); this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) {
      for (let i = 0; i < ch.length; i++) {
        this.buf[this.n++] = ch[i];
        if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice(0)); this.n = 0; }
      }
    }
    return true;
  }
}
registerProcessor("aasan-capture", AasanCapture);
`;

interface Capture {
  stop(): void;
  level(): number;
}

/** Mic → Float32 chunks via an AudioWorklet, or a ScriptProcessor where worklets are missing. */
async function startCapture(onChunk: (samples: Float32Array, rate: number) => void): Promise<Capture> {
  const media = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
  const ctx = new AudioContext();
  if (ctx.state === "suspended") await ctx.resume().catch(() => {});
  const src = ctx.createMediaStreamSource(media);
  let rms = 0;
  const handle = (s: Float32Array) => {
    let sum = 0;
    for (const v of s) sum += v * v;
    rms = Math.sqrt(sum / Math.max(1, s.length));
    onChunk(s, ctx.sampleRate);
  };
  let node: AudioNode;
  if (ctx.audioWorklet && typeof AudioWorkletNode !== "undefined") {
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    await ctx.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    const w = new AudioWorkletNode(ctx, "aasan-capture");
    w.port.onmessage = (e: MessageEvent<Float32Array>) => handle(e.data);
    node = w;
  } else {
    const sp = ctx.createScriptProcessor(2048, 1, 1);
    sp.onaudioprocess = (e) => handle(new Float32Array(e.inputBuffer.getChannelData(0)));
    node = sp;
  }
  // A muted sink keeps the graph pulling audio without playing the mic back.
  const sink = ctx.createGain();
  sink.gain.value = 0;
  src.connect(node);
  node.connect(sink);
  sink.connect(ctx.destination);
  return {
    level: () => Math.min(1, rms * 4),
    stop: () => {
      try {
        src.disconnect();
        node.disconnect();
      } catch {
        /* already disconnected */
      }
      media.getTracks().forEach((t) => t.stop());
      void ctx.close().catch(() => {});
    },
  };
}

/** Opens the mic and the stream; resolves once the server has started listening (rejects with an Error whose
 * message is the error code if it can't). Reconnects by itself after a dropped socket or the session-length cap. */
export async function openVoiceStream(lang: Lang, onEvent: (ev: StreamEvent) => void, log: (m: string) => void = () => {}): Promise<VoiceStream> {
  let ws: WebSocket | null = null;
  let stopped = false;
  let down: Downsampler | null = null;
  let retries = 0;
  let retryTimer: ReturnType<typeof setTimeout> | undefined;

  const connect = (first: boolean) =>
    new Promise<void>((resolve, reject) => {
      void (async () => {
        const token = (await ensureFreshAccess()) ?? useAuth.getState().access;
        if (stopped) return resolve();
        const proto = location.protocol === "https:" ? "wss" : "ws";
        const sock = new WebSocket(`${proto}://${location.host}/ws/voice-stream/`);
        sock.binaryType = "arraybuffer";
        ws = sock;
        let live = false;
        let fatal = false;
        sock.onopen = () => sock.send(JSON.stringify({ type: "auth", token }));
        sock.onmessage = (e) => {
          if (typeof e.data !== "string") return;
          const ev = JSON.parse(e.data) as StreamEvent;
          if (ev.type === "ready") {
            sock.send(JSON.stringify({ type: "start", lang }));
            return;
          }
          if (ev.type === "started") {
            live = true;
            retries = 0;
            log(`stream started (${lang})`);
            resolve();
            return;
          }
          if (ev.type === "error") {
            log(`stream error: ${ev.code}`);
            if (!FATAL_STREAM_ERRORS.has(ev.code)) return; // session cap, dropped upstream…: the close reconnects
            fatal = true;
            if (!live && first) return reject(new Error(ev.code));
          }
          onEvent(ev);
        };
        sock.onclose = (e) => {
          if (ws === sock) ws = null;
          if (stopped) return;
          log(`stream closed (${e.code})`);
          if (fatal) return;
          if (!live && first) return reject(new Error("stream_unavailable"));
          // Dropped or capped (30 min): reconnect quietly, a few times.
          if (retries++ >= 5) return onEvent({ type: "error", code: "stream_closed" });
          retryTimer = setTimeout(() => void connect(false).catch(() => {}), Math.min(5000, 300 * 2 ** retries));
        };
      })();
    });

  const capture = await startCapture((samples, rate) => {
    down ??= new Downsampler(rate);
    const frames = down.push(samples);
    if (!ws || ws.readyState !== WebSocket.OPEN) return; // audio while (re)connecting is dropped, never queued
    for (const f of frames) ws.send(f);
  });
  try {
    await connect(true);
  } catch (e) {
    capture.stop();
    throw e;
  }
  return {
    level: () => capture.level(),
    stop: () => {
      stopped = true;
      clearTimeout(retryTimer);
      capture.stop();
      const sock = ws;
      ws = null;
      if (sock) {
        try {
          if (sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ type: "stop" }));
          sock.close();
        } catch {
          /* already closed */
        }
      }
    },
  };
}
