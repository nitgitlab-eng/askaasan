/**
 * Listening and speaking engines. "server" engines go through Aasan's API
 * (keys stay server-side); "browser" engines use the Web Speech API.
 */
import { api } from "@/lib/api";
import { useAuth } from "@/stores/auth";

import { detectLang } from "./text";

export type Lang = "en" | "ta";
export const BCP47: Record<Lang, string> = { en: "en-IN", ta: "ta-IN" };

export interface VoiceConfig {
  /** streaming: the server can stream listening live (Deepgram) over ws/voice-stream/ — live conversation. */
  stt: { engine: "browser" | "server"; provider: string; streaming?: boolean };
  tts: { engine: "browser" | "server"; provider: string };
  /** "Speaking: Tamil" — Tamil lines use it when set up, else `tts`. */
  tts_ta?: { engine: "browser" | "server"; provider: string };
  /** A live voice call (LiveKit + the server's voice agent) can be made. */
  live?: boolean;
}

export const fetchVoiceConfig = () => api<VoiceConfig>("/api/voice/config/");

/** Who is speaking a clip: the narrator (Listen, explainer) or one of the two podcast hosts (two different voices). */
export type VoiceRole = "narrator" | "host_a" | "host_b";
export interface ClipRequest { text: string; lang: Lang; voice_role: VoiceRole }
export interface Clip { url: string; cached: boolean; mime?: string; duration_ms?: number | null }

/** One shared, cached server clip (generated once for everyone). `warm` = the lines after it, made in the background. */
export async function fetchClip(req: ClipRequest, warm?: ClipRequest[]): Promise<Clip> {
  const r = await authedFetch("/api/voice/clip/", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(warm?.length ? { ...req, warm } : req),
  });
  return r.json() as Promise<Clip>;
}

export class VoiceApiError extends Error {
  code: string;
  status: number;

  constructor(code: string, status = 0) {
    super(code);
    this.code = code;
    this.status = status;
  }
}

/** One clip of server speech (keys stay server-side). */
export async function fetchSpeech(text: string, lang: Lang): Promise<Blob> {
  const r = await authedFetch("/api/voice/speak/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, lang }) });
  return r.blob();
}

async function authedFetch(path: string, init: RequestInit) {
  const doFetch = () =>
    fetch(path, { ...init, headers: { ...(init.headers ?? {}), Authorization: `Bearer ${useAuth.getState().access}` } });
  let res = await doFetch();
  if (res.status === 401) {
    await api("/api/users/me/").catch(() => {}); // triggers token refresh
    res = await doFetch();
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new VoiceApiError(data.code ?? `http_${res.status}`, res.status);
  }
  return res;
}

// ── Speaking ───────────────────────────────────────────────────────────

let sharedCtx: AudioContext | null = null;

/** One AudioContext for the whole app (browsers cap how many may exist); re-woken on any user gesture. */
export function audioContext(): AudioContext {
  if (!sharedCtx) {
    sharedCtx = new AudioContext();
    const wake = () => {
      if (sharedCtx?.state === "suspended") void sharedCtx.resume().catch(() => {});
    };
    for (const ev of ["pointerdown", "keydown", "touchend"]) window.addEventListener(ev, wake, { capture: true, passive: true });
  }
  return sharedCtx;
}

/** Call synchronously inside a click/tap so later (post-await) playback is allowed, esp. on iOS/Safari. */
export function unlockAudio() {
  if (typeof AudioContext === "undefined") return;
  try {
    const ctx = audioContext();
    if (ctx.state === "suspended") void ctx.resume().catch(() => {});
  } catch {
    /* audio unavailable */
  }
}

let voicesWait: Promise<SpeechSynthesisVoice[]> | null = null;

/** Chrome fills getVoices() asynchronously; wait for 'voiceschanged' (≤ ~1 s) before choosing a voice. */
export function waitForVoices(maxMs = 1000): Promise<SpeechSynthesisVoice[]> {
  const now = speechSynthesis.getVoices();
  if (now.length) return Promise.resolve(now);
  voicesWait ??= new Promise<SpeechSynthesisVoice[]>((resolve) => {
    const done = () => {
      speechSynthesis.removeEventListener?.("voiceschanged", done);
      clearTimeout(timer);
      voicesWait = null;
      resolve(speechSynthesis.getVoices());
    };
    const timer = setTimeout(done, maxMs);
    speechSynthesis.addEventListener?.("voiceschanged", done);
  });
  return voicesWait;
}

export interface Speaker {
  /** Queue one sentence; resolves when it finishes or is cancelled. */
  speak(text: string): void;
  cancel(): void;
  readonly busy: boolean;
  /** 0..1 loudness of what is playing right now (for Kili's beak). */
  level(): number;
  onIdle?: () => void;
  onError?: (code: string) => void;
  /** A queued sentence starts playing now (live captions). */
  onStart?: (text: string) => void;
  /** Live call: the words being spoken right now, in step with the voice (replaces the sentence caption). */
  onCaption?: (text: string) => void;
  /** Live call: the reply is complete, nothing more will be added. */
  end?(): void;
  /** Live call: hang up. */
  dispose?(): void;
}

export function pickBrowserVoice(lang: Lang): SpeechSynthesisVoice | undefined {
  const voices = speechSynthesis.getVoices();
  return (
    voices.find((v) => v.lang === BCP47[lang]) ??
    voices.find((v) => v.lang.startsWith(lang)) ??
    (lang === "en" ? voices.find((v) => v.lang.startsWith("en")) : undefined)
  );
}

export function browserSpeaker(rate = 1): Speaker {
  let pending = 0;
  let pulse = 0;
  let generation = 0;
  const self: Speaker = {
    speak(text) {
      const gen = generation;
      pending++;
      const say = () => {
        if (gen !== generation) return;
        const lang = detectLang(text);
        const u = new SpeechSynthesisUtterance(text);
        u.lang = BCP47[lang];
        const voice = pickBrowserVoice(lang);
        if (voice) u.voice = voice;
        u.rate = rate;
        u.onboundary = () => (pulse = 1);
        u.onstart = () => self.onStart?.(text);
        u.onend = u.onerror = () => {
          pending = Math.max(0, pending - 1);
          if (!pending) self.onIdle?.();
        };
        speechSynthesis.speak(u);
      };
      // Speak synchronously when voices are ready (keeps the user gesture); else wait for them first.
      if (speechSynthesis.getVoices().length) say();
      else void waitForVoices().then(say);
    },
    cancel() {
      generation++;
      pending = 0;
      speechSynthesis.cancel();
    },
    get busy() {
      return pending > 0;
    },
    level() {
      // Browser TTS exposes no audio; fake a beak pulse from word boundaries.
      pulse *= 0.82;
      return pending ? 0.25 + pulse * 0.75 : 0;
    },
  };
  return self;
}

/** Server voice is unusable right now (unconfigured, upstream down, offline): speak with the browser instead. */
function shouldFallBack(e: unknown) {
  if (!(e instanceof VoiceApiError)) return true; // network / decode failure
  return e.status === 503 || e.status === 502 || e.code === "provider_not_configured" || e.code === "use_browser_engine";
}

export function serverSpeaker(rate = 1): Speaker {
  let analyser: AnalyserNode | null = null;
  let buf = new Uint8Array(0);
  const output = () => {
    const ctx = audioContext();
    if (!analyser) {
      analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      analyser.connect(ctx.destination);
      buf = new Uint8Array(analyser.fftSize);
    }
    return { ctx, analyser };
  };
  // Fetch in parallel, play strictly in order.
  let chain: Promise<void> = Promise.resolve();
  let generation = 0;
  let pending = 0;
  let current: AudioBufferSourceNode | null = null;
  // Once the server voice fails, this speaker stays on the browser voice for the rest of its life.
  let fallback: Speaker | null = null;
  const toBrowser = () => {
    if (!fallback) {
      fallback = browserSpeaker(rate);
      fallback.onIdle = () => {
        if (!pending) self.onIdle?.();
      };
      fallback.onStart = (t) => self.onStart?.(t);
    }
    return fallback;
  };
  // A sentence the server voice can't speak (422: e.g. a Tamil line with an English-only voice like Deepgram's, or an
  // English line when only Tamil has a server voice) is read by the browser voice just this once; the next sentences
  // still use the server voice.
  let oneOff: Speaker | null = null;
  const browserOnce = () => {
    if (!oneOff) {
      oneOff = browserSpeaker(rate);
      oneOff.onIdle = () => {
        if (!pending && !fallback?.busy) self.onIdle?.();
      };
      oneOff.onStart = (t) => self.onStart?.(t);
    }
    return oneOff;
  };

  const self: Speaker = {
    speak(text) {
      unlockAudio();
      const gen = generation;
      pending++;
      const audio = fallback
        ? null
        : authedFetch("/api/voice/speak/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, lang: detectLang(text) }),
        }).then((r) => r.arrayBuffer());
      audio?.catch(() => {}); // handled in the chain
      chain = chain.then(async () => {
        try {
          if (gen !== generation) return;
          if (fallback || !audio) {
            toBrowser().speak(text);
            return;
          }
          const bytes = await audio;
          if (gen !== generation) return;
          const { ctx, analyser } = output();
          const decoded = await ctx.decodeAudioData(bytes);
          if (gen !== generation) return;
          if (ctx.state === "suspended") await ctx.resume();
          await new Promise<void>((done) => {
            const src = ctx.createBufferSource();
            src.buffer = decoded;
            src.playbackRate.value = rate;
            src.connect(analyser);
            src.onended = () => done();
            current = src;
            src.start();
            self.onStart?.(text);
          });
        } catch (e) {
          if (gen !== generation) return;
          if (e instanceof VoiceApiError && (e.status === 422 || e.code === "use_browser_engine")) browserOnce().speak(text);
          else if (shouldFallBack(e)) toBrowser().speak(text);
          else self.onError?.(e instanceof VoiceApiError ? e.code : "tts_failed");
        } finally {
          current = null;
          if (gen === generation) {
            pending = Math.max(0, pending - 1);
            if (!pending && !fallback?.busy) self.onIdle?.();
          }
        }
      });
    },
    cancel() {
      generation++;
      pending = 0;
      fallback?.cancel();
      oneOff?.cancel();
      try {
        current?.stop();
      } catch {
        /* already stopped */
      }
      current = null;
      chain = Promise.resolve();
    },
    get busy() {
      return pending > 0 || !!fallback?.busy || !!oneOff?.busy;
    },
    level() {
      if (fallback?.busy) return fallback.level();
      if (oneOff?.busy) return oneOff.level();
      if (!current || !analyser) return 0;
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += ((v - 128) / 128) ** 2;
      return Math.min(1, Math.sqrt(sum / buf.length) * 4);
    },
  };
  return self;
}

// ── Listening ──────────────────────────────────────────────────────────

/** Records one utterance from an existing mic stream (server STT path). */
export function startClip(stream: MediaStream) {
  const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  const chunks: Blob[] = [];
  const started = performance.now();
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  rec.start(250);
  return {
    stop: () =>
      new Promise<{ blob: Blob; seconds: number }>((resolve) => {
        rec.onstop = () => resolve({ blob: new Blob(chunks, { type: rec.mimeType || "audio/webm" }), seconds: (performance.now() - started) / 1000 });
        rec.stop();
      }),
    discard: () => rec.state !== "inactive" && rec.stop(),
  };
}

export async function serverTranscribe(blob: Blob, seconds: number, lang?: Lang): Promise<string> {
  const form = new FormData();
  form.append("audio", blob, "speech.webm");
  form.append("seconds", seconds.toFixed(1));
  if (lang) form.append("lang", lang);
  const res = await authedFetch("/api/voice/transcribe/", { method: "POST", body: form });
  return ((await res.json()) as { text: string }).text;
}

type SR = typeof window extends { SpeechRecognition: infer T } ? T : never;
export const BrowserRecognition: (new () => SpeechRecognitionLike) | undefined =
  typeof window !== "undefined"
    ? ((window as unknown as { SpeechRecognition?: SR; webkitSpeechRecognition?: SR }).SpeechRecognition ??
      (window as unknown as { webkitSpeechRecognition?: SR }).webkitSpeechRecognition) as never
    : undefined;

export interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
}
