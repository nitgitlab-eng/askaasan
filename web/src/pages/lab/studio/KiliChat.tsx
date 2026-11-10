import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Send, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { LabCourse } from "@/lib/lab";
import { studio, type Change, type ChatMsg } from "@/lib/studio";
import { mascot } from "@/mascot/store";

/** 'Build with Kili': chat → proposed changes → accept/reject each one (applied changes are a single undo step). */
export function KiliChat({ c, set }: { c: LabCourse; set: (c: LabCourse) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["kili-chat", c.id], queryFn: () => studio.chat(c.id) });
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [picked, setPicked] = useState<Record<number, Set<number>>>({});
  const box = useRef<HTMLDivElement>(null);
  const msgs = data?.messages ?? [];
  const openIdx = (m: ChatMsg) => (m.changes ?? []).map((_, i) => i).filter((i) => !(m.applied ?? []).includes(i) && !(m.rejected ?? []).includes(i) && !m.errors?.[String(i)]);
  // Undecided proposals start selected (also after a reload); the teacher unticks what they don't want.
  const selected = (turn: number, m: ChatMsg) => picked[turn] ?? new Set(openIdx(m));
  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight }); // braces: scrollTo may return a Promise in newer browsers
  }, [msgs.length]);

  const titleOf = (id: number, kind: "section" | "lesson") => {
    for (const s of c.sections ?? []) {
      if (kind === "section" && s.id === id) return s.title;
      const b = s.subsections.find((x) => x.id === id);
      if (kind === "lesson" && b) return b.title;
    }
    return `#${id}`;
  };
  const describe = (ch: Change) => {
    const where = ch.lesson_id ? titleOf(ch.lesson_id, "lesson") : ch.section_id ? titleOf(ch.section_id, "section") : ch.ref >= 0 ? t("studio.chat.newSection") : "";
    return t(`studio.op.${ch.op}`, { title: ch.title, where, type: ch.activity_type ? t(`lesson.types.${ch.activity_type}`, { defaultValue: ch.activity_type }) : "" });
  };

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    setErr("");
    mascot.react("thinking", 0);
    try {
      const r = await studio.say(c.id, text.trim());
      qc.setQueryData(["kili-chat", c.id], r);
      setText("");
      mascot.react("talking", 1500);
    } catch (x) {
      setErr(x instanceof ApiError && x.status === 402 ? t("studio.chat.limit") : t("mentor.errors.generic"));
      mascot.react("hmm");
    } finally {
      setBusy(false);
    }
  }
  async function apply(turn: number, m: ChatMsg) {
    const sel = selected(turn, m);
    const open = openIdx(m);
    setBusy(true);
    try {
      const r = await studio.apply(c.id, turn, open.filter((i) => sel.has(i)), open.filter((i) => !sel.has(i)));
      qc.setQueryData(["kili-chat", c.id], { messages: r.messages });
      set(r.course);
      void qc.invalidateQueries({ queryKey: ["lab-lesson"] });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="flex max-h-[80vh] flex-col gap-3">
      <div>
        <h3 className="font-display text-lg font-bold">{t("studio.buildWithKili")}</h3>
        <p className="text-xs text-muted">{t("studio.chat.sub")}</p>
      </div>
      <div ref={box} className="min-h-40 flex-1 space-y-3 overflow-y-auto pr-1" aria-live="polite">
        {!msgs.length && (
          <div className="space-y-1">
            {(t("studio.chat.examples", { returnObjects: true }) as string[]).map((ex) => (
              <button key={ex} onClick={() => setText(ex)} className="block w-full rounded-xl border border-line px-3 py-1.5 text-left text-sm hover:border-accent">{ex}</button>
            ))}
          </div>
        )}
        {msgs.map((m, turn) => (
          <div key={turn} className={cn("space-y-2", m.role === "user" && "flex justify-end")}>
            <p className={cn("w-fit max-w-[95%] whitespace-pre-line rounded-2xl px-3 py-2 text-sm", m.role === "user" ? "bg-accent text-accent-ink" : "border border-line bg-surface")}>{m.content}</p>
            {m.role === "assistant" && !!m.changes?.length && (
              <div className="space-y-1.5 rounded-2xl border-2 border-dashed border-accent/40 p-2">
                {m.changes.map((ch, i) => {
                  const applied = m.applied?.includes(i), rejected = m.rejected?.includes(i), error = m.errors?.[String(i)];
                  const on = selected(turn, m).has(i);
                  return (
                    <label key={i} className={cn("flex items-start gap-2 rounded-xl px-2 py-1 text-sm", applied && "bg-good/10", (rejected || error) && "opacity-60")}>
                      {applied ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-good" /> : rejected || error ? <X className="mt-0.5 h-4 w-4 shrink-0 text-muted" /> : (
                        <input type="checkbox" className="mt-1" checked={on} onChange={() => setPicked((p) => {
                          const s = new Set(p[turn] ?? selected(turn, m));
                          if (s.has(i)) s.delete(i);
                          else s.add(i);
                          return { ...p, [turn]: s };
                        })} />
                      )}
                      <span className="min-w-0">
                        <span className="font-medium">{describe(ch)}</span>
                        {ch.text && ch.op !== "write_lesson" && <span className="block text-xs text-muted">{ch.text.slice(0, 140)}</span>}
                        {ch.op === "write_lesson" && <span className="block text-xs text-muted">{t("studio.chat.chars", { count: ch.text.length })}</span>}
                        {error && <span className="block text-xs text-bad">{t(`studio.chat.err.${error}`, { defaultValue: error })}</span>}
                      </span>
                    </label>
                  );
                })}
                {openIdx(m).length > 0 && (
                  <div className="flex gap-2 pt-1">
                    <Button className="py-1.5 text-sm" loading={busy} onClick={() => void apply(turn, m)}>{t("studio.chat.apply", { n: selected(turn, m).size })}</Button>
                    <Button variant="ghost" className="py-1.5 text-sm" onClick={() => setPicked((p) => ({ ...p, [turn]: new Set() }))}>{t("studio.chat.none")}</Button>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {busy && <p className="text-sm text-muted">{t("mentor.thinking")}</p>}
      </div>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      <form onSubmit={(e) => void send(e)} className="flex gap-2">
        <input value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} placeholder={t("studio.chat.ph")} aria-label={t("studio.chat.ph")}
          className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent" />
        <button disabled={!text.trim() || busy} aria-label={t("mentor.send")} className="rounded-xl bg-accent p-2.5 text-accent-ink disabled:opacity-50"><Send className="h-4 w-4" /></button>
      </form>
    </Card>
  );
}
