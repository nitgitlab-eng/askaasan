import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Paperclip, PencilRuler, Redo2, Sparkles, Undo2, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { learner } from "@/lib/learner";

/** Learners shaping their own course: AI "add a section", hidden items, undo/redo, attached sources. */
export function EditCourse({ courseId, onChanged }: { courseId: number; onChanged: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const key = ["course-edit", courseId];
  const { data } = useQuery({ queryKey: key, queryFn: () => learner.editState(courseId) });
  const { data: docs } = useQuery({ queryKey: ["docs"], queryFn: () => api<{ id: number; title: string }[]>("/api/docs/") });
  const [ask, setAsk] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: key });
    onChanged();
  };
  const run = async (fn: () => Promise<unknown>, ok = "") => {
    setBusy(true);
    setMsg("");
    try { await fn(); if (ok) setMsg(ok); refresh(); }
    catch (e) { setMsg(e instanceof ApiError && e.status === 429 ? t("courseEdit.budget") : e instanceof ApiError && e.status === 409 ? t("courseEdit.nothing") : t("mentor.errors.generic")); }
    finally { setBusy(false); }
  };
  if (!data) return null;
  const attached = new Set(data.sources.map((s) => s.id));
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold"><PencilRuler className="h-5 w-5 text-accent" /> {t("courseEdit.title")}</h2>
        <div className="flex gap-2">
          <Button variant="outline" disabled={!data.can_undo || busy} title={data.undo_label} onClick={() => void run(() => learner.step(courseId, "undo"))}><Undo2 className="h-4 w-4" /> {t("courseEdit.undo")}</Button>
          <Button variant="outline" disabled={!data.can_redo || busy} title={data.redo_label} onClick={() => void run(() => learner.step(courseId, "redo"))}><Redo2 className="h-4 w-4" /> {t("courseEdit.redo")}</Button>
        </div>
      </div>
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (ask.trim().length >= 3) void run(async () => { await learner.addSection(courseId, ask.trim()); setAsk(""); }, t("courseEdit.added")); }}>
        <input value={ask} onChange={(e) => setAsk(e.target.value)} maxLength={400} placeholder={t("courseEdit.askPh")}
          className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2" aria-label={t("courseEdit.ask")} />
        <Button type="submit" loading={busy} disabled={ask.trim().length < 3}><Sparkles className="h-4 w-4" /> {t("courseEdit.add")}</Button>
      </form>
      <p className="text-xs text-muted">{t("courseEdit.hideHint")}</p>
      {data.hidden.length > 0 && (
        <div>
          <p className="mb-1 text-sm font-semibold">{t("courseEdit.hidden")}</p>
          <ul className="flex flex-wrap gap-2">
            {data.hidden.map((h) => (
              <li key={`${h.kind}-${h.id}`}>
                <button type="button" className="flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-sm hover:border-accent" onClick={() => void run(() => learner.setHidden(courseId, h.kind, h.id, false))}>
                  <Eye className="h-3.5 w-3.5" /> {h.title}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <p className="mb-1 flex items-center gap-1.5 text-sm font-semibold"><Paperclip className="h-4 w-4" /> {t("courseEdit.sources")}</p>
        <p className="mb-2 text-xs text-muted">{t("courseEdit.sourcesHint")}</p>
        <ul className="flex flex-wrap gap-2">
          {data.sources.map((s) => (
            <li key={s.id} className="flex items-center gap-1 rounded-full bg-accent/15 px-2.5 py-1 text-sm">
              {s.title}
              <button type="button" aria-label={t("courseEdit.remove")} onClick={() => void run(() => learner.removeSource(courseId, s.id))}><X className="h-3.5 w-3.5" /></button>
            </li>
          ))}
          {docs?.filter((d) => !attached.has(d.id)).slice(0, 8).map((d) => (
            <li key={d.id}><button type="button" className="rounded-full border border-dashed border-line px-2.5 py-1 text-sm hover:border-accent" onClick={() => void run(() => learner.addSource(courseId, d.id))}>+ {d.title}</button></li>
          ))}
        </ul>
      </div>
      {msg && <p role="status" className="text-sm text-muted">{msg}</p>}
    </Card>
  );
}
