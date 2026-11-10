/**
 * Lightweight energy-based voice activity detector.
 * `VadMachine` is pure (feed it RMS frames) so it can be unit-tested;
 * `startMicVad` wires it to a live microphone.
 */
export type VadEvent = "speech-start" | "speech-end" | "speech-cancel";

export interface VadOptions {
  frameMs: number;
  attackMs: number; // continuous loud time before speech-start
  releaseMs: number; // continuous quiet time before speech-end
  minSpeechMs: number; // ignore blips shorter than this
  ratio: number; // threshold = noiseFloor * ratio
  minThreshold: number;
}

export const DEFAULT_VAD: VadOptions = { frameMs: 20, attackMs: 60, releaseMs: 900, minSpeechMs: 250, ratio: 3, minThreshold: 0.012 };

export class VadMachine {
  private floor = 0.005;
  private loudMs = 0;
  private quietMs = 0;
  private speechMs = 0;
  speaking = false;
  /** Multiplies the threshold (raise while the mentor is talking to avoid echo). */
  sensitivity = 1;

  private o: VadOptions;

  constructor(o: VadOptions = DEFAULT_VAD) {
    this.o = o;
  }

  get threshold() {
    return Math.max(this.o.minThreshold, this.floor * this.o.ratio) * this.sensitivity;
  }

  /** Feed one frame's RMS (0..1). Returns an event when state flips. */
  feed(rms: number): VadEvent | null {
    const loud = rms > this.threshold;
    // Track background noise only while not speaking (slow up, fast down).
    if (!this.speaking && !loud) this.floor = rms < this.floor ? this.floor * 0.9 + rms * 0.1 : this.floor * 0.995 + rms * 0.005;

    if (!this.speaking) {
      this.loudMs = loud ? this.loudMs + this.o.frameMs : 0;
      if (this.loudMs >= this.o.attackMs) {
        this.speaking = true;
        this.speechMs = this.loudMs;
        this.quietMs = 0;
        return "speech-start";
      }
      return null;
    }
    this.speechMs += this.o.frameMs;
    this.quietMs = loud ? 0 : this.quietMs + this.o.frameMs;
    if (this.quietMs >= this.o.releaseMs) {
      this.speaking = false;
      this.loudMs = 0;
      const long = this.speechMs - this.quietMs >= this.o.minSpeechMs;
      return long ? "speech-end" : "speech-cancel"; // blip (cough, tap): discard the clip
    }
    return null;
  }
}

export interface MicVad {
  stream: MediaStream;
  machine: VadMachine;
  level: () => number;
  stop: () => void;
}

export async function startMicVad(onEvent: (e: VadEvent) => void, overrides: Partial<VadOptions> = {}): Promise<MicVad> {
  const opts = { ...DEFAULT_VAD, ...overrides };
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const ctx = new AudioContext();
  const src = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  src.connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  const machine = new VadMachine(opts);
  let lastRms = 0;
  const timer = setInterval(() => {
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (const v of buf) sum += v * v;
    lastRms = Math.sqrt(sum / buf.length);
    const ev = machine.feed(lastRms);
    if (ev) onEvent(ev);
  }, opts.frameMs);
  return {
    stream,
    machine,
    level: () => lastRms,
    stop: () => {
      clearInterval(timer);
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close();
    },
  };
}
