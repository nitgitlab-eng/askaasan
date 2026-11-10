import { Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { study } from "@/lib/study";

/** Select any text inside → "Explain this" → Kili explains it simply, right there. */
export function ExplainSelection({ subsectionId, lang, children }: { subsectionId: number; lang?: string; children: ReactNode }) {
  const { t } = useTranslation();
  const box = useRef<HTMLDivElement>(null);
  const [sel, setSel] = useState<{ text: string; x: number; y: number } | null>(null);
  const [out, setOut] = useState<{ q: string; a: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onUp = () => {
      const s = window.getSelection();
      const text = s?.toString().trim() ?? "";
      if (!s || !text || text.length < 2 || text.length > 600 || !box.current?.contains(s.anchorNode)) return setSel(null);
      const r = s.getRangeAt(0).getBoundingClientRect();
      const host = box.current.getBoundingClientRect();
      setSel({ text, x: Math.min(Math.max(8, r.left - host.left + r.width / 2), host.width - 8), y: r.top - host.top });
    };
    document.addEventListener("mouseup", onUp);
    document.addEventListener("touchend", onUp);
    return () => {
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("touchend", onUp);
    };
  }, []);

  async function explain() {
    if (!sel) return;
    setBusy(true);
    try {
      const r = await study.explain(sel.text, subsectionId, lang);
      setOut({ q: sel.text, a: r.text });
    } catch {
      setOut({ q: sel.text, a: t("mentor.errors.generic") });
    } finally {
      setBusy(false);
      setSel(null);
      window.getSelection()?.removeAllRanges();
    }
  }

  return (
    <div ref={box} className="relative">
      {children}
      {sel && (
        <button onMouseDown={(e) => e.preventDefault()} onClick={() => void explain()} disabled={busy}
          style={{ left: sel.x, top: Math.max(0, sel.y - 40) }}
          className="absolute z-10 flex -translate-x-1/2 items-center gap-1 rounded-full bg-accent px-3 py-1.5 text-xs font-semibold text-accent-ink shadow-lg">
          <Sparkles className="h-3.5 w-3.5" /> {busy ? t("mentor.thinking") : t("explain.button")}
        </button>
      )}
      {out && (
        <div role="note" className="mt-4 rounded-2xl border-2 border-accent/40 bg-accent/5 p-3 text-sm">
          <div className="mb-1 flex items-start justify-between gap-2">
            <p className="font-semibold">“{out.q.length > 80 ? `${out.q.slice(0, 80)}…` : out.q}”</p>
            <button onClick={() => setOut(null)} aria-label={t("common.close")}><X className="h-4 w-4 text-muted" /></button>
          </div>
          <p>{out.a}</p>
        </div>
      )}
      <p className="mt-2 text-xs text-muted">{t("explain.tip")}</p>
    </div>
  );
}
