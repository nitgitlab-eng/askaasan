/** Tiny WebAudio blips — no audio assets needed. Respect prefs.sound_effects. */
let ctx: AudioContext | null = null;
let enabled = true;

export const setSfxEnabled = (v: boolean) => (enabled = v);

function tone(freq: number, start: number, dur: number, type: OscillatorType = "sine", gain = 0.08) {
  if (!ctx) return;
  const o = ctx.createOscillator();
  const g = ctx.createGain();
  o.type = type;
  o.frequency.value = freq;
  g.gain.setValueAtTime(gain, ctx.currentTime + start);
  g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur);
  o.connect(g).connect(ctx.destination);
  o.start(ctx.currentTime + start);
  o.stop(ctx.currentTime + start + dur);
}

export function sfx(kind: "correct" | "wrong" | "pop" | "levelup") {
  if (!enabled || typeof window === "undefined" || !("AudioContext" in window)) return;
  ctx ??= new AudioContext();
  if (kind === "correct") [523, 659, 784].forEach((f, i) => tone(f, i * 0.08, 0.18, "triangle"));
  if (kind === "wrong") [330, 262].forEach((f, i) => tone(f, i * 0.12, 0.2, "sine", 0.05));
  if (kind === "pop") tone(880, 0, 0.06, "square", 0.03);
  if (kind === "levelup") [523, 659, 784, 1047].forEach((f, i) => tone(f, i * 0.1, 0.25, "triangle"));
}
