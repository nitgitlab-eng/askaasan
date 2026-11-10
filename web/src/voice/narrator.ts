/**
 * Narrator for Listen mode, explainer videos and lesson podcasts: reads a list of parts (lesson sections, video scenes,
 * podcast turns) aloud.
 *
 * Server voice: each part becomes a few whole, sentence-joined clips (never split mid-sentence). Each clip is a shared,
 * cached file on the server (`/api/voice/clip/`), so a replay, or another learner, starts instantly. The first clip is
 * made on tap; the server pre-makes the rest of the episode/lesson in the background, and the player asks for the next
 * 2 clips ahead while one plays. Tamil lines use the Tamil voice when the admin set one up.
 * Browser voice: used when no server voice can say a line (any Indian language the device has).
 *
 * Nothing is fetched until play() is first called.
 */
import { fetchClip, fetchVoiceConfig, waitForVoices, type ClipRequest, type Lang, type VoiceConfig, type VoiceRole } from "./engines";
import { speakable } from "./text";

export interface NarratorState { part: number; playing: boolean; loading: boolean; ended: boolean; error: string }
export interface NarratorOptions {
  /** Who reads each part (podcasts: host_a / host_b, two different voices). Default: the narrator. */
  roles?: VoiceRole[];
  onPartDone?: (part: number) => void;
  /** A short pause before a part read by a different speaker (podcast turns). */
  turnGapMs?: number;
}

/** Same limit as the server's MAX_TTS_CHARS: one clip. */
export const CLIP_MAX = 600;
/** Clips asked for ahead of the one playing. */
export const PREFETCH = 2;

/** Browser voices for a language (exact BCP-47 match first, then same base language). */
export function voicesFor(all: SpeechSynthesisVoice[], bcp: string): SpeechSynthesisVoice[] {
  const exact = all.filter((x) => x.lang === bcp);
  return exact.length ? exact : all.filter((x) => x.lang.startsWith(bcp.slice(0, 2)));
}

// Tanglish lessons are written in Tamil script (see LANG_RULE), so they need a Tamil voice.
const BCP: Record<string, string> = { en: "en-IN", ta: "ta-IN", hi: "hi-IN", te: "te-IN", kn: "kn-IN", ml: "ml-IN", bn: "bn-IN", mr: "mr-IN", gu: "gu-IN", tanglish: "ta-IN" };
const TAMIL = /[஀-௿]/;

/** Browser voice language for a lesson language. */
export const browserLang = (lang: string) => BCP[lang] ?? "en-IN";
/** Server voice language for a lesson language. */
export const serverLang = (lang: string): Lang => (lang === "ta" || lang === "tanglish" ? "ta" : "en");
/** The server voice language of one line: Tamil script always needs the Tamil voice. */
export const lineLang = (text: string, lang: string): Lang => (TAMIL.test(text) ? "ta" : serverLang(lang));

// A silent clip played inside the user's tap so the element may play later, after awaits (iOS/Safari).
const SILENCE = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

/** Split text into whole sentences joined into clips of at most `max` characters (a single over-long sentence is cut
 * at the last space before the limit). */
export function sentences(text: string, max = CLIP_MAX): string[] {
  const parts = speakable(text).replace(/\s+/g, " ").split(/(?<=[.!?।॥])\s+/);
  const out: string[] = [];
  for (let p of parts) {
    p = p.trim();
    if (!p) continue;
    const last = out[out.length - 1];
    if (last !== undefined && last.length + 1 + p.length <= max) { out[out.length - 1] = `${last} ${p}`; continue; }
    while (p.length > max) {
      const cut = p.lastIndexOf(" ", max);
      const at = cut > 0 ? cut : max;
      out.push(p.slice(0, at).trim());
      p = p.slice(at).trim();
    }
    if (p) out.push(p);
  }
  return out;
}

interface Seg { part: number; text: string; req: ClipRequest }

export class Narrator {
  private segs: Seg[][];
  private flat: Seg[];
  private state: NarratorState = { part: 0, playing: false, loading: false, ended: false, error: "" };
  private chunk = 0;
  private audio: HTMLAudioElement | null = null;
  private el: HTMLAudioElement | null = null;
  private urls = new Map<string, Promise<string>>();
  private config: Promise<VoiceConfig | null> | null = null;
  private serverOff = new Set<Lang>();
  private warmed = false;
  private gen = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;
  autoplay = true;
  rate = 1;

  private lang: string;
  private onState: (s: NarratorState) => void;
  private opts: NarratorOptions;

  constructor(parts: string[], lang: string, onState: (s: NarratorState) => void, opts: NarratorOptions = {}) {
    this.lang = lang;
    this.onState = onState;
    this.opts = opts;
    this.segs = parts.map((p, part) => sentences(p).map((text) => ({
      part, text, req: { text, lang: lineLang(text, lang), voice_role: opts.roles?.[part] ?? "narrator" },
    })));
    this.flat = this.segs.flat();
  }

  get parts() {
    return this.segs.length;
  }

  private set(p: Partial<NarratorState>) {
    this.state = { ...this.state, ...p };
    this.onState(this.state);
  }

  /** The voice config, fetched once, on the first play. */
  private voiceConfig() {
    this.config ??= (this.lang === "en" || this.lang === "ta" || this.lang === "tanglish")
      ? fetchVoiceConfig().catch(() => null)
      : Promise.resolve(null);
    return this.config;
  }

  private async serverFor(seg: Seg): Promise<boolean> {
    const c = await this.voiceConfig();
    if (!c || this.serverOff.has(seg.req.lang)) return false;
    if (seg.req.lang === "ta") return c.tts_ta?.engine === "server" || c.tts.engine === "server";
    return c.tts.engine === "server";
  }

  private clip(seg: Seg, warm?: Seg[]): Promise<string> {
    const key = `${seg.req.voice_role}|${seg.req.lang}|${seg.text}`;
    let p = this.urls.get(key);
    if (!p) {
      p = fetchClip(seg.req, warm?.map((s) => s.req)).then((c) => c.url);
      p.catch(() => this.urls.delete(key));
      this.urls.set(key, p);
    }
    return p;
  }

  /** Create and prime the one audio element synchronously, while we are still inside the user's gesture. */
  private unlock() {
    if (this.el || typeof Audio === "undefined") return;
    const a = new Audio();
    a.src = SILENCE;
    void a.play()?.catch(() => {});
    this.el = a;
  }

  play(part = this.state.part, chunk = 0, offset = 0): void {
    this.unlock();
    this.stopSound();
    const gen = ++this.gen;
    if (part >= this.segs.length) return this.set({ playing: false, ended: true });
    this.chunk = chunk;
    this.set({ part, playing: true, ended: false, error: "" });
    const seg = this.segs[part][chunk];
    if (!seg) return this.advance(gen);
    void this.serverFor(seg).then((server) => (gen === this.gen ? (server ? this.playServer(gen, seg, offset) : this.playBrowser(gen)) : undefined));
  }

  private advance(gen: number, heard = true): void {
    if (gen !== this.gen) return;
    const { part } = this.state;
    if (this.chunk + 1 < this.segs[part].length) return this.play(part, this.chunk + 1);
    if (heard) this.opts.onPartDone?.(part);
    if (this.autoplay && part + 1 < this.segs.length) {
      const roles = this.opts.roles;
      const gap = this.opts.turnGapMs && roles && roles[part + 1] !== roles[part] ? this.opts.turnGapMs : 0;
      if (!gap) return this.play(part + 1, 0);
      clearTimeout(this.timer);
      this.timer = setTimeout(() => gen === this.gen && this.play(part + 1, 0), gap); // a breath between speakers
      return;
    }
    this.set({ playing: false, ended: part + 1 >= this.segs.length });
  }

  /** Ask for the next PREFETCH clips while this one plays; the first request also hands the server the rest to warm. */
  private ahead(seg: Seg) {
    const i = this.flat.indexOf(seg);
    for (const next of this.flat.slice(i + 1, i + 1 + PREFETCH)) {
      void this.serverFor(next).then((s) => (s ? this.clip(next).catch(() => {}) : undefined));
    }
  }

  private async playServer(gen: number, seg: Seg, offset: number) {
    this.set({ loading: true });
    try {
      let warm: Seg[] | undefined;
      if (!this.warmed) {
        this.warmed = true;
        const i = this.flat.indexOf(seg);
        warm = this.flat.slice(i + 1 + PREFETCH); // the prefetch window is asked for directly
      }
      const url = await this.clip(seg, warm);
      this.ahead(seg);
      if (gen !== this.gen) return;
      const a = this.el ?? new Audio();
      this.el = a;
      a.src = url;
      a.playbackRate = this.rate;
      a.onended = () => this.advance(gen);
      this.audio = a;
      if (offset) a.addEventListener("loadedmetadata", () => gen === this.gen && (a.currentTime = Math.max(0, Math.min(offset, a.duration - 0.2))), { once: true });
      await a.play();
      this.set({ loading: false });
    } catch (e) {
      if (gen !== this.gen) return;
      this.set({ loading: false });
      // No server voice for this language (e.g. Tamil with an English-only voice): the browser reads it, and the next
      // lines in that language go straight to the browser too.
      const code = (e as { code?: string })?.code;
      if (code === "use_browser_engine" || code === "unsupported_language" || code === "provider_not_configured") this.serverOff.add(seg.req.lang);
      this.playBrowser(gen);
    }
  }

  private playBrowser(gen: number) {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return this.set({ playing: false, error: "no_voice" });
    // Chrome has no voices on the first call; wait for them so the right language voice is picked.
    if (!speechSynthesis.getVoices().length) {
      void waitForVoices().then(() => gen === this.gen && this.speakBrowser(gen));
      return;
    }
    this.speakBrowser(gen);
  }

  private speakBrowser(gen: number) {
    const seg = this.segs[this.state.part][this.chunk];
    if (!seg) return this.advance(gen);
    const u = new SpeechSynthesisUtterance(seg.text);
    u.lang = seg.req.lang === "ta" ? "ta-IN" : browserLang(this.lang);
    const vs = voicesFor(speechSynthesis.getVoices(), u.lang);
    const v = vs.length ? vs[(seg.req.voice_role === "host_b" ? 1 : 0) % vs.length] : undefined; // second host: another voice
    if (v) u.voice = v;
    u.rate = this.rate;
    let started = false;
    const stop = (error: string) => {
      if (gen !== this.gen) return;
      this.gen++;
      clearInterval(keepAlive);
      speechSynthesis.cancel();
      this.set({ playing: false, loading: false, error });
    };
    // Chrome pauses long speech after ~15 s; nudging it keeps it going.
    const keepAlive = setInterval(() => {
      if (gen !== this.gen) return clearInterval(keepAlive);
      if (speechSynthesis.speaking && !speechSynthesis.paused) { speechSynthesis.pause(); speechSynthesis.resume(); }
    }, 10000);
    u.onstart = () => { started = true; };
    u.onend = () => { clearInterval(keepAlive); if (gen === this.gen) this.advance(gen); };
    // A real failure stops and says so — never race silently through the parts.
    u.onerror = (e) => { clearInterval(keepAlive); if (e.error !== "interrupted" && e.error !== "canceled") stop("no_voice"); };
    setTimeout(() => { if (!started && gen === this.gen) stop("no_voice"); }, 5000);
    speechSynthesis.cancel(); // clear anything stuck in the queue
    speechSynthesis.speak(u);
  }

  setAutoplay(on: boolean) {
    this.autoplay = on;
  }

  setRate(rate: number) {
    this.rate = rate;
    if (this.audio) this.audio.playbackRate = rate;
  }

  pause() {
    this.gen++;
    clearTimeout(this.timer);
    if (this.audio) this.audio.pause();
    else if (typeof window !== "undefined" && "speechSynthesis" in window) speechSynthesis.cancel();
    this.set({ playing: false });
  }

  resume() {
    if (this.audio && this.audio.currentTime > 0 && !this.audio.ended) {
      const a = this.audio;
      const gen = ++this.gen;
      a.onended = () => this.advance(gen);
      void a.play();
      this.set({ playing: true });
    } else this.play(this.state.part, this.chunk);
  }

  /** ±seconds within the current clip (server voice); by clip with the browser voice. */
  seek(seconds: number) {
    const { part } = this.state;
    if (this.audio && !this.audio.ended && this.audio.duration) {
      const t = this.audio.currentTime + seconds;
      if (t >= 0 && t < this.audio.duration) {
        this.audio.currentTime = t;
        return;
      }
      if (t < 0 && this.chunk > 0) return this.play(part, this.chunk - 1);
      if (t < 0) return this.play(part, 0);
      return this.advance(this.gen, false);
    }
    const step = seconds < 0 ? -1 : 1;
    this.play(part, Math.max(0, Math.min(this.segs[part].length - 1, this.chunk + step)));
  }

  goTo(part: number) {
    this.play(Math.max(0, Math.min(this.segs.length - 1, part)), 0);
  }

  replay() {
    this.play(this.state.part, 0);
  }

  private stopSound() {
    clearTimeout(this.timer);
    if (this.audio) {
      this.audio.onended = null;
      this.audio.pause();
      this.audio = null;
    }
    if (typeof window !== "undefined" && "speechSynthesis" in window) speechSynthesis.cancel();
  }

  destroy() {
    this.gen++;
    this.stopSound();
    if (this.el) this.el.removeAttribute("src");
    this.el = null;
  }
}
