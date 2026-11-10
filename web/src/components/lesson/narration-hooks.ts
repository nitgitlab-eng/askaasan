import { useEffect, useMemo, useRef, useState } from "react";

import { Narrator, type NarratorOptions, type NarratorState } from "@/voice/narrator";

const IDLE: NarratorState = { part: 0, playing: false, loading: false, ended: false, error: "" };

/** Read `current` only in a tap handler: the Narrator is made on first use, so nothing is fetched before Play. */
export interface LazyNarrator { readonly current: Narrator }

/** One Narrator for a list of parts, created lazily on the first tap and rebuilt when the parts or language change.
 * `opts` is read when it is created. */
export function useNarrator(parts: string[], lang: string, opts?: NarratorOptions) {
  const key = `${lang}|${parts.join("\u0001")}`;
  const [st, setSt] = useState<{ key: string; s: NarratorState }>({ key, s: IDLE });
  const inst = useRef<{ key: string; n: Narrator } | null>(null);
  const latest = useRef({ parts, lang, opts, key });
  useEffect(() => { latest.current = { parts, lang, opts, key }; });
  useEffect(() => () => {
    inst.current?.n.destroy();
    inst.current = null;
  }, [key]);
  const n = useMemo<LazyNarrator>(() => ({
    get current() {
      const { parts: p, lang: l, opts: o, key: k } = latest.current;
      if (inst.current?.key !== k) {
        inst.current?.n.destroy();
        const narrator = new Narrator(p, l, (s) => setSt({ key: k, s }), {
          roles: o?.roles, turnGapMs: o?.turnGapMs, onPartDone: (i) => latest.current.opts?.onPartDone?.(i),
        });
        inst.current = { key: k, n: narrator };
      }
      return inst.current.n;
    },
  }), []);
  return { st: st.key === key ? st.s : IDLE, n };
}

/** Split lesson Markdown into narratable sections: by headings, else ~3 paragraphs each. */
export function lessonParts(md: string, title: string): { label: string; text: string }[] {
  const blocks = md.split(/\n(?=#{1,4}\s)/).map((b) => b.trim()).filter(Boolean);
  if (blocks.length > 1) {
    return blocks.map((b, i) => {
      const m = b.match(/^#{1,4}\s+(.+)\n?/);
      return { label: m ? m[1].trim() : i === 0 ? title : `${i + 1}`, text: b };
    });
  }
  const paras = md.split(/\n{2,}/).filter((p) => p.trim());
  const out: { label: string; text: string }[] = [];
  for (let i = 0; i < paras.length; i += 3) out.push({ label: `${out.length + 1}`, text: paras.slice(i, i + 3).join("\n\n") });
  return out.length ? out : [{ label: title, text: md }];
}

