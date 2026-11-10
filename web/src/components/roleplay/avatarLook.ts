/**
 * Pure helpers for the 3D role-play avatar: a deterministic look per character
 * (same character → same avatar, different characters → different avatars) and
 * a light-weight emotion read of the conversation. No three.js here, so this
 * file is cheap to import and easy to unit-test.
 */

export type HairStyle = "short" | "side" | "curly" | "bun" | "long" | "braid" | "bald";
export type Emotion = "neutral" | "happy" | "concerned" | "thinking";

export interface AvatarLook {
  skin: string;
  hair: string;
  hairStyle: HairStyle;
  /** Main clothing colour. */
  top: string;
  /** Secondary colour for dupatta / scarf / cap. */
  trim: string;
  iris: string;
  lips: string;
  glasses: boolean;
  dupatta: boolean;
  scarf: boolean;
  cap: boolean;
  moustache: boolean;
  beard: boolean;
  bindi: boolean;
  earrings: boolean;
  /** Formal collar (interviewers, officers, bank staff…). */
  collar: boolean;
}

export interface LookSeed {
  name: string;
  persona?: string;
  title?: string;
}

// Warm, Indian-inclusive skin range (light wheatish → deep brown).
export const SKIN_TONES = ["#f1c9a5", "#e5b48c", "#d9a074", "#c68a5e", "#b0764c", "#9a633e", "#7f4f31", "#653d26"];
export const HAIR_COLOURS = ["#1b1512", "#231a15", "#2e2019", "#3b2a20", "#4a3426", "#6b6460"];
export const TOP_COLOURS = ["#2563eb", "#0f766e", "#b91c1c", "#7c3aed", "#ca8a04", "#db2777", "#15803d", "#c2410c", "#0e7490", "#4338ca", "#9f1239", "#475569"];
export const TRIM_COLOURS = ["#f59e0b", "#e11d48", "#10b981", "#f97316", "#a855f7", "#facc15", "#06b6d4", "#fb7185"];
const IRIS = ["#2b1a10", "#3a2414", "#4b3020", "#1f1611"];

/** FNV-1a 32-bit — stable across browsers and runs. */
export function hashString(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** Tiny seeded PRNG (mulberry32) so each trait draws a fresh, reproducible number. */
function rng(seed: number) {
  let a = seed || 1;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const has = (text: string, words: string[]) => words.some((w) => new RegExp(`(^|[^\\p{L}])${w}([^\\p{L}]|$)`, "iu").test(text));

const FEM = ["she", "her", "hers", "woman", "lady", "girl", "mother", "amma", "akka", "aunty", "auntie", "madam", "ma'am", "mrs", "ms", "miss", "sister", "teacher-amma", "grandmother", "paati", "wife", "daughter", "அம்மா", "அக்கா", "பாட்டி", "அவள்", "அவர்கள்", "திருமதி"];
const MASC = ["he", "him", "his", "man", "gentleman", "boy", "father", "appa", "anna", "uncle", "sir", "mr", "brother", "thatha", "grandfather", "husband", "son", "அப்பா", "அண்ணா", "தாத்தா", "அவன்", "திரு"];
const FEM_NAMES = /(a|i|ee|ya|mi|thi|vi|ni|ri|shree|shri|lakshmi|devi)$/i;

function genderHint(seed: LookSeed, r: () => number): "f" | "m" {
  const persona = `${seed.persona ?? ""}`;
  const f = has(persona, FEM) || has(seed.name, ["mrs", "ms", "miss", "madam", "amma", "akka", "aunty"]);
  const m = has(persona, MASC) || has(seed.name, ["mr", "sir", "anna", "uncle", "thatha"]);
  if (f && !m) return "f";
  if (m && !f) return "m";
  const first = seed.name.trim().split(/\s+/)[0] ?? "";
  if (/^[a-z]/i.test(first)) return FEM_NAMES.test(first) ? "f" : "m";
  return r() < 0.5 ? "f" : "m";
}

const pick = <T,>(xs: readonly T[], r: () => number) => xs[Math.floor(r() * xs.length) % xs.length];

/** Deterministic avatar look for a scenario character. */
export function avatarLook(seed: LookSeed): AvatarLook {
  const key = `${seed.name.trim().toLowerCase()}|${(seed.title ?? "").trim().toLowerCase()}`;
  const r = rng(hashString(key));
  const ctx = `${seed.name} ${seed.persona ?? ""} ${seed.title ?? ""}`;
  const g = genderHint(seed, r);

  const skin = pick(SKIN_TONES, r);
  const hair = pick(HAIR_COLOURS, r);
  const top = pick(TOP_COLOURS, r);
  let trim = pick(TRIM_COLOURS, r);
  if (trim === top) trim = TRIM_COLOURS[(TRIM_COLOURS.indexOf(trim) + 1) % TRIM_COLOURS.length];
  const iris = pick(IRIS, r);
  const roll = Array.from({ length: 8 }, () => r());

  const elderly = has(ctx, ["grandmother", "grandfather", "elderly", "old", "retired", "senior", "paati", "thatha", "பாட்டி", "தாத்தா"]);
  // Formal dress comes from who the character *is* (name/title/role words), not from who they talk about.
  const formal = has(`${seed.name} ${seed.title ?? ""}`, ["interview", "bank", "office", "hr"]) || has(seed.persona ?? "", ["interviewer", "recruiter", "officer", "banker", "doctor", "lawyer", "principal", "director", "executive", "clerk"]);
  const studious = has(ctx, ["professor", "teacher", "librarian", "accountant", "scientist", "engineer", "doctor", "glasses", "spectacles", "கண்ணாடி"]);
  const outdoor = has(ctx, ["driver", "auto", "rickshaw", "cricket", "farmer", "delivery", "vendor", "coach", "cap", "conductor", "mechanic", "guard"]);

  const hairStyle: HairStyle =
    g === "f" ? pick(["bun", "long", "braid", "braid", "long", "curly"] as const, r) : elderly && roll[0] < 0.5 ? "bald" : pick(["short", "side", "curly", "short"] as const, r);

  return {
    skin,
    hair: elderly ? "#8d8a86" : hair,
    hairStyle,
    top,
    trim,
    iris,
    lips: g === "f" ? "#a8505a" : "#8a4b45",
    glasses: studious || elderly ? roll[1] < 0.8 : roll[1] < 0.18,
    dupatta: g === "f" && !formal && roll[2] < 0.65,
    scarf: g === "m" && !formal && roll[2] < 0.2,
    cap: outdoor ? roll[3] < 0.75 : g === "m" && !formal && roll[3] < 0.08,
    moustache: g === "m" && roll[4] < 0.6,
    beard: g === "m" && roll[5] < 0.25,
    bindi: g === "f" && roll[6] < 0.6,
    earrings: g === "f" && roll[7] < 0.7,
    collar: formal,
  };
}

const HAPPY = ["thank", "thanks", "great", "welcome", "glad", "happy", "wonderful", "nice", "perfect", "excellent", "congratulations", "sure", "of course", "lovely", "good", "awesome", "pleasure", "நன்றி", "மகிழ்ச்சி", "அருமை", "நல்லது", "சூப்பர்", "வாங்க", "வணக்கம்", "சரி"];
const CONCERNED = ["sorry", "unfortunately", "problem", "issue", "worried", "concern", "concerned", "can't", "cannot", "not possible", "angry", "upset", "disappointed", "complaint", "refund", "delay", "delayed", "broken", "wrong", "unhappy", "mistake", "மன்னிக்கவும்", "பிரச்சனை", "முடியாது", "கவலை", "தவறு", "கோபம்"];

const score = (text: string, words: string[]) => words.reduce((n, w) => n + (text.includes(w) ? 1 : 0), 0);

/**
 * Emotion for the character from conversation state: `thinking` while waiting
 * for a reply, otherwise a keyword read of the character's latest line.
 */
export function inferEmotion(text: string | null | undefined, opts: { waiting?: boolean } = {}): Emotion {
  if (opts.waiting) return "thinking";
  const s = (text ?? "").toLowerCase();
  if (!s.trim()) return "neutral";
  const h = score(s, HAPPY) + (/[😊😀😄🙂🎉👍]/u.test(s) ? 1 : 0) + (/!\s*$/.test(s.trim()) ? 0.5 : 0);
  const c = score(s, CONCERNED) * 1.2 + (/[😟😞😠🙁]/u.test(s) ? 1 : 0);
  if (c > h && c >= 1) return "concerned";
  if (h > c && h >= 1) return "happy";
  return "neutral";
}
