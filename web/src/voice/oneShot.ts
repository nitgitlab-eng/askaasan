/** One-shot voice helpers for short turn-based uses (decision-tree stories): speak a line, then hear one answer. */
import {
  BCP47,
  BrowserRecognition,
  browserSpeaker,
  fetchVoiceConfig,
  serverSpeaker,
  serverTranscribe,
  startClip,
  unlockAudio,
  type Lang,
  type Speaker,
  type VoiceConfig,
} from "./engines";

let cfg: Promise<VoiceConfig> | null = null;
const config = () => (cfg ??= fetchVoiceConfig().catch(() => ({ stt: { engine: "browser", provider: "browser" }, tts: { engine: "browser", provider: "browser" } }) as VoiceConfig));

let active: { sp: Speaker; done: () => void } | null = null;

/** Speak text and resolve when finished (or after a safety timeout). */
export async function speakAndWait(text: string, rate = 1): Promise<void> {
  unlockAudio(); // still inside the user's tap
  const c = await config();
  const sp = c.tts.engine === "server" ? serverSpeaker(rate) : browserSpeaker(rate);
  await new Promise<void>((resolve) => {
    const timer = setTimeout(() => done(), Math.min(60000, 4000 + text.length * 90));
    const done = () => {
      clearTimeout(timer);
      if (active?.sp === sp) active = null;
      resolve();
    };
    active?.sp.cancel();
    active?.done();
    active = { sp, done };
    sp.onIdle = done;
    sp.onError = done;
    sp.speak(text);
  });
}

/** Stop whatever speakAndWait is saying (server or browser voice). */
export function stopSpeaking() {
  const a = active;
  active = null;
  a?.sp.cancel();
  a?.done();
  try {
    speechSynthesis.cancel();
  } catch {
    /* no browser TTS */
  }
}

/** Listen for one answer. Browser recognition when configured/available; otherwise record until silence and use server STT. */
export async function listenOnce(lang: Lang, maxMs = 8000): Promise<string> {
  const c = await config();
  if (c.stt.engine === "browser" && BrowserRecognition) {
    return new Promise((resolve, reject) => {
      const r = new BrowserRecognition!();
      r.lang = BCP47[lang];
      r.continuous = false;
      r.interimResults = false;
      let text = "";
      r.onresult = (e) => { text = e.results[e.resultIndex]?.[0]?.transcript ?? text; };
      r.onerror = (e) => (e.error === "no-speech" ? resolve("") : reject(new Error(e.error)));
      r.onend = () => resolve(text.trim());
      r.start();
      setTimeout(() => r.stop(), maxMs);
    });
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  try {
    const clip = startClip(stream);
    await untilSilence(stream, maxMs);
    const { blob, seconds } = await clip.stop();
    return (await serverTranscribe(blob, seconds, lang)).trim();
  } finally {
    stream.getTracks().forEach((t) => t.stop());
  }
}

/** Resolve after ~1.2 s of quiet once speech has started, or at maxMs. */
function untilSilence(stream: MediaStream, maxMs: number): Promise<void> {
  const ctx = new AudioContext();
  const an = ctx.createAnalyser();
  an.fftSize = 1024;
  ctx.createMediaStreamSource(stream).connect(an);
  const buf = new Float32Array(an.fftSize);
  const start = performance.now();
  let spoke = false;
  let quietSince = 0;
  return new Promise((resolve) => {
    const tick = () => {
      an.getFloatTimeDomainData(buf);
      const rms = Math.sqrt(buf.reduce((s, v) => s + v * v, 0) / buf.length);
      const now = performance.now();
      if (rms > 0.03) {
        spoke = true;
        quietSince = 0;
      } else if (spoke) {
        quietSince ||= now;
      }
      if ((spoke && quietSince && now - quietSince > 1200) || now - start > maxMs) {
        void ctx.close();
        resolve();
      } else requestAnimationFrame(tick);
    };
    tick();
  });
}
