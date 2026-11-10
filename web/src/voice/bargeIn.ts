/**
 * Barge-in decisions for live conversation: while Aasan is talking, does what the mic heard mean the learner wants
 * to cut in, or is it just Aasan's own voice leaking back (echo)?
 */

/** Words that always cut in, said anywhere in the utterance (Deepgram may spell "Aasan" a few ways). */
const WAKE = ["aasan", "aasaan", "asan", "hasan", "ஆசான்", "ஆசான", "stop", "wait", "நிறுத்து", "நிறுத்துங்க", "நிறுத்துங்கள்"];

/** Lower-case words, punctuation and zero-width marks dropped (Tamil letters and vowel signs kept). */
export function words(text: string): string[] {
  return text
    .normalize("NFC")
    .toLowerCase()
    .replace(/[\u200b-\u200d\ufeff]/g, "")
    .replace(/[^\p{L}\p{M}\p{N}\s']/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
}

function bigrams(w: string): string[] {
  const out: string[] = [];
  for (let i = 0; i < w.length - 1; i++) out.push(w.slice(i, i + 2));
  return out;
}

/** Dice similarity of two words' letter pairs: 1 for the same word, ~0.6+ for the same word with another ending. */
export function similar(a: string, b: string): number {
  if (a === b) return 1;
  const x = bigrams(a);
  const y = bigrams(b);
  if (!x.length || !y.length) return 0;
  const pool = [...y];
  let hits = 0;
  for (const g of x) {
    const i = pool.indexOf(g);
    if (i >= 0) {
      hits++;
      pool.splice(i, 1);
    }
  }
  return (2 * hits) / (x.length + y.length);
}

export function hasWakeWord(text: string): boolean {
  return words(text).some((w) => WAKE.includes(w));
}

/**
 * Echo: most of the heard words (60%+, or `ratio`) are words Aasan is saying now or just said. The recogniser rarely
 * hears its own voice back word for word, Tamil least of all (endings change, words merge or split), so a heard word
 * counts when it is close to a said word or sits inside the said text, not only when it matches exactly.
 */
export function isEcho(heard: string, spoken: string[], ratio = 0.6): boolean {
  const saidWords = spoken.flatMap(words);
  const w = words(heard);
  if (!w.length || !saidWords.length) return false;
  const said = new Set(saidWords);
  const joined = saidWords.join("");
  const phrase = w.join("");
  if (phrase.length >= 6 && joined.includes(phrase)) return true; // the same words, only split differently
  const hit = (x: string) =>
    said.has(x) || (x.length >= 4 && joined.includes(x)) || (x.length >= 3 && saidWords.some((s) => similar(x, s) >= 0.6));
  return w.filter(hit).length / w.length >= ratio;
}

export type BargeIn = "wake" | "speech" | null;

/**
 * While Aasan talks: "wake" when a wake word was said (unless it is only Aasan saying that word itself), "speech" when
 * 2+ words that are not an echo of what Aasan is saying, else null (ignore it).
 */
export function decideBargeIn(heard: string, spoken: string[]): BargeIn {
  const w = words(heard);
  if (!w.length) return null;
  const echo = isEcho(heard, spoken);
  if (hasWakeWord(heard)) {
    const said = new Set(spoken.flatMap(words));
    const wakeSaidByAasan = w.filter((x) => WAKE.includes(x)).every((x) => said.has(x));
    if (!(echo && wakeSaidByAasan)) return "wake";
  }
  if (w.length >= 2 && !echo) return "speech";
  return null;
}

/** "Aasan, what is a prompt?" → "what is a prompt?" (wake words and the punctuation after them, at the start only). */
export function stripWake(text: string): string {
  let t = text.trim();
  for (;;) {
    const m = t.match(/^([\p{L}\p{M}']+)[\s,.!?;:—-]*/u);
    if (!m || !WAKE.includes(m[1].toLowerCase())) return t;
    t = t.slice(m[0].length).trim();
  }
}
