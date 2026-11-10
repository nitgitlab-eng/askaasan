/** Text helpers for speaking streamed Markdown replies naturally. */

const TAMIL = /[஀-௿]/g;

/** "ta" when Tamil script dominates the letters, else "en". */
export function detectLang(text: string): "ta" | "en" {
  const tamil = text.match(TAMIL)?.length ?? 0;
  const latin = text.match(/[A-Za-z]/g)?.length ?? 0;
  return tamil > 0 && tamil >= latin * 0.6 ? "ta" : "en";
}

export const CODE_CUE = "I've put the code on screen.";

/** Strip Markdown so the voice doesn't read symbols; replace code with a cue and drop tables. */
export function speakable(md: string, codeCue = CODE_CUE): string {
  return md
    .replace(/```[\s\S]*?```/g, ` ${codeCue} `)
    .replace(/```[\s\S]*$/, ` ${codeCue} `) // a reply cut off inside a code block
    .replace(/^\s*\|.*\|?\s*$/gm, "") // table rows and their |---| rulers
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/(\*\*|__|\*|_|~~)(.+?)\1/g, "$2")
    .replace(/\$([^$]+)\$/g, "$1")
    .replace(/\p{Extended_Pictographic}️?/gu, "")
    .replace(/\s+/g, " ")
    .trim();
}

const BOUNDARY = /([.!?।]+["')\]]?)(\s+)|(\n{2,})|(\n\s*[-*+]\s)/g;

/**
 * Incremental sentence splitter for a growing streamed string.
 * Feed the full text so far; returns newly completed sentences and keeps the tail.
 * Unclosed code fences are held back until they close.
 */
export class SentenceStream {
  private consumed = 0;
  private codeCue: string;
  private early: boolean;

  /** `early`: a long first sentence is let go at its first clause break (", " after 40+ characters), so a spoken
   * reply starts sooner; everything after it still splits on whole sentences. */
  constructor(codeCue = CODE_CUE, opts: { early?: boolean } = {}) {
    this.codeCue = codeCue;
    this.early = !!opts.early;
  }

  push(fullText: string): string[] {
    const pending = fullText.slice(this.consumed);
    const fences = (pending.match(/```/g) ?? []).length;
    if (fences % 2 === 1) {
      // Speak whatever precedes the open fence; hold the code block.
      const at = pending.indexOf("```", pending.lastIndexOf("```") === pending.indexOf("```") ? 0 : pending.lastIndexOf("```"));
      return this.cut(fullText, this.consumed + Math.max(0, at), false);
    }
    return this.cut(fullText, fullText.length, false);
  }

  /** Call when the stream ends to flush the remaining tail. */
  flush(fullText: string): string[] {
    return this.cut(fullText, fullText.length, true);
  }

  private cut(fullText: string, limit: number, final: boolean): string[] {
    const region = fullText.slice(this.consumed, limit);
    const out: string[] = [];
    let last = 0;
    // Never split inside a fenced code block: the whole block becomes one piece, spoken as the code cue.
    const fences: [number, number][] = [];
    for (let at = region.indexOf("```"); at >= 0; ) {
      const close = region.indexOf("```", at + 3);
      fences.push([at, close < 0 ? region.length : close + 3]);
      at = close < 0 ? -1 : region.indexOf("```", close + 3);
    }
    BOUNDARY.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = BOUNDARY.exec(region))) {
      const hit = m.index;
      if (fences.some(([a, b]) => hit >= a && hit < b)) continue;
      const end = m.index + (m[1]?.length ?? 0) + (m[2]?.length ?? 0) + (m[3]?.length ?? 0) + (m[4] ? 1 : 0);
      const piece = region.slice(last, end);
      if (piece.trim().length >= 2) {
        out.push(piece);
        last = end;
      }
    }
    if (this.early && !final && this.consumed === 0 && !out.length && !fences.length) {
      const clause = /[,;:]\s|\s[—–]\s/g;
      let c: RegExpExecArray | null;
      while ((c = clause.exec(region))) {
        if (c.index < 40) continue;
        const end = c.index + c[0].length;
        out.push(region.slice(0, end));
        last = end;
        break;
      }
    }
    if (final && region.slice(last).trim()) {
      out.push(region.slice(last));
      last = region.length;
    }
    this.consumed += last;
    return out.map((s) => speakable(s, this.codeCue)).filter(Boolean);
  }
}
