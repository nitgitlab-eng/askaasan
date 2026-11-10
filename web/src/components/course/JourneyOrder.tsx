import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, GripVertical, Sparkles } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { journey, move, moveTo, type OrderSuggestion } from "@/lib/journey";
import type { CourseSummary } from "@/lib/learn";

/** Reorder my learning journey on /learn: drag, arrow buttons, or ↑/↓ on a focused row. Saved right away. */
export function JourneyOrder({ courses, onDone }: { courses: CourseSummary[]; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const [status, setStatus] = useState("");

  const save = async (next: CourseSummary[]) => {
    qc.setQueryData(["courses"], next);
    setStatus("");
    try {
      await journey.saveOrder(next.map((c) => c.id));
      setStatus(t("lj.order.saved"));
    } catch {
      setStatus(t("mentor.errors.generic"));
      void qc.invalidateQueries({ queryKey: ["courses"] });
    }
  };
  const step = (i: number, d: number) => {
    const next = move(courses, i, d);
    if (next !== courses) void save(next);
  };

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">{t("lj.order.hint")}</p>
        <Button variant="outline" onClick={onDone}>{t("lj.order.done")}</Button>
      </div>
      <ol className="space-y-1.5">
        {courses.map((c, i) => (
          <li key={c.id} draggable onDragStart={() => setDragFrom(i)} onDragOver={(e) => e.preventDefault()}
            onDrop={() => { if (dragFrom !== null) void save(moveTo(courses, dragFrom, i)); setDragFrom(null); }}
            className={cn("flex items-center gap-2 rounded-xl border-2 bg-surface px-2 py-1.5", dragFrom === i ? "border-accent opacity-60" : "border-line")}>
            <button type="button" aria-label={t("lj.order.drag", { title: c.title })} className="cursor-grab text-muted"
              onKeyDown={(e) => {
                if (e.key === "ArrowUp" || e.key === "ArrowDown") {
                  e.preventDefault();
                  step(i, e.key === "ArrowUp" ? -1 : 1);
                }
              }}>
              <GripVertical className="h-4 w-4" />
            </button>
            <span className="w-6 text-center text-sm font-bold text-muted">{i + 1}</span>
            <span className="min-w-0 flex-1 truncate font-medium">{c.title}</span>
            <button type="button" aria-label={t("lj.order.up", { title: c.title })} disabled={i === 0} onClick={() => step(i, -1)}
              className="rounded-lg p-1 text-muted hover:text-accent disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button>
            <button type="button" aria-label={t("lj.order.down", { title: c.title })} disabled={i === courses.length - 1} onClick={() => step(i, 1)}
              className="rounded-lg p-1 text-muted hover:text-accent disabled:opacity-30"><ArrowDown className="h-4 w-4" /></button>
          </li>
        ))}
      </ol>
      <p role="status" className="text-xs text-muted">{status}</p>
      <SuggestOrder courses={courses} onAccept={(next) => void save(next)} />
    </Card>
  );
}

/** "Suggest an order": AI proposes an order for my active courses; nothing changes until I accept. */
function SuggestOrder({ courses, onAccept }: { courses: CourseSummary[]; onAccept: (next: CourseSummary[]) => void }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [sug, setSug] = useState<OrderSuggestion | null>(null);
  const [err, setErr] = useState("");
  const ask = async () => {
    setBusy(true);
    setErr("");
    try { setSug(await journey.suggestOrder()); }
    catch (e) { setErr(e instanceof ApiError && e.status === 409 ? t("lj.order.needTwo") : t("lj.order.error")); }
    finally { setBusy(false); }
  };
  if (!sug) {
    return (
      <div>
        <Button variant="outline" loading={busy} onClick={() => void ask()}><Sparkles className="h-4 w-4" /> {busy ? t("lj.order.suggesting") : t("lj.order.suggest")}</Button>
        {err && <p role="alert" className="mt-1 text-sm text-bad">{err}</p>}
      </div>
    );
  }
  const accept = () => {
    const pos = new Map(sug.order.map((id, i) => [id, i]));
    // Suggested (active) courses first in the suggested order; the rest keep their place after them.
    const next = [...courses.filter((c) => pos.has(c.id)).sort((a, b) => pos.get(a.id)! - pos.get(b.id)!), ...courses.filter((c) => !pos.has(c.id))];
    onAccept(next);
    setSug(null);
  };
  return (
    <div className="space-y-2 rounded-xl bg-surface-2 p-3">
      <p className="font-semibold">{t("lj.order.title")}</p>
      {sug.note && <p className="text-sm">{sug.note}</p>}
      <ol className="list-decimal space-y-1 pl-5 text-sm">
        {sug.courses.map((c) => (
          <li key={c.id}><span className="font-medium">{c.title}</span> <span className="text-xs text-muted">· {t("lj.order.progress", { done: c.done, count: c.total })}</span>
            {c.reason && <span className="block text-xs text-muted">{c.reason}</span>}</li>
        ))}
      </ol>
      <div className="flex flex-wrap gap-2">
        <Button onClick={accept}>{t("lj.order.accept")}</Button>
        <Button variant="ghost" onClick={() => setSug(null)}>{t("lj.order.reject")}</Button>
      </div>
    </div>
  );
}
