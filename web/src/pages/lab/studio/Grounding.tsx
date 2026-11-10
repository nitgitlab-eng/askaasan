import { useQuery } from "@tanstack/react-query";
import { Globe, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { LabCourse } from "@/lib/lab";
import { studio } from "@/lib/studio";

/** What the AI writes from: a saved pipeline (preset), the author's own notes, and web research with sources. */
export function Grounding({ c, set }: { c: LabCourse; set: (c: LabCourse) => void }) {
  const { t } = useTranslation();
  const { data: presets } = useQuery({ queryKey: ["presets"], queryFn: studio.presets });
  const { data: docs } = useQuery({ queryKey: ["docs"], queryFn: () => api<{ id: number; title: string }[]>("/api/docs/") });
  const a = c.authoring;
  const [topic, setTopic] = useState(a?.research?.topic ?? c.title);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const attached = new Set((a?.documents ?? []).map((d) => d.id));

  async function research() {
    setBusy(true);
    setErr("");
    try {
      set(await studio.research(c.id, topic));
    } catch (e) {
      const code = e instanceof ApiError ? String(e.data?.code ?? "") : "";
      setErr(code.startsWith("web_search") ? t("studio.ground.noSearch") : e instanceof ApiError && e.status === 402 ? t("studio.chat.limit") : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-5">
      <div>
        <h3 className="font-display text-lg font-bold">{t("studio.grounding")}</h3>
        <p className="text-xs text-muted">{t("studio.ground.sub")}</p>
      </div>
      <section className="space-y-1">
        <p className="text-sm font-semibold">{t("studio.ground.preset")}</p>
        <select value={a?.preset?.id ?? ""} onChange={async (e) => set(await studio.usePreset(c.id, e.target.value ? Number(e.target.value) : null))}
          className="w-full rounded-xl border-2 border-line bg-surface px-2 py-1.5 text-sm" aria-label={t("studio.ground.preset")}>
          <option value="">{t("studio.ground.noPreset")}</option>
          {presets?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <Link to="/lab#presets" className="text-xs font-semibold text-accent">{t("studio.ground.managePresets")}</Link>
      </section>
      <section className="space-y-1">
        <p className="text-sm font-semibold">{t("studio.ground.docs")}</p>
        {!docs?.length ? <p className="text-xs text-muted">{t("studio.ground.noDocs")} <Link to="/documents" className="font-semibold text-accent">{t("nav.documents")}</Link></p> : (
          <ul className="max-h-40 space-y-1 overflow-y-auto">
            {docs.map((d) => (
              <li key={d.id}>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={attached.has(d.id)} disabled={!attached.has(d.id) && attached.size >= 5}
                    onChange={async () => { const next = new Set(attached); if (next.has(d.id)) next.delete(d.id); else next.add(d.id); set(await studio.setDocuments(c.id, [...next])); }} />
                  <span className="truncate">{d.title}</span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="space-y-2">
        <p className="flex items-center gap-1.5 text-sm font-semibold"><Globe className="h-4 w-4 text-accent" /> {t("studio.ground.research")}</p>
        <div className="flex gap-2">
          <input value={topic} onChange={(e) => setTopic(e.target.value)} maxLength={300} aria-label={t("studio.ground.topic")}
            className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-1.5 text-sm outline-none focus:border-accent" />
          <Button variant="outline" loading={busy} disabled={topic.trim().length < 3} onClick={() => void research()}><Search className="h-4 w-4" /> {t("studio.ground.go")}</Button>
        </div>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        {a?.research && (
          <div className="space-y-2 rounded-xl bg-surface-2 p-3 text-sm">
            <div className="flex items-start justify-between gap-2">
              <p className="font-semibold">{a.research.topic}</p>
              <button onClick={async () => set(await studio.clearResearch(c.id))} aria-label={t("lab.delete")} className="text-muted hover:text-bad"><Trash2 className="h-4 w-4" /></button>
            </div>
            <p className="max-h-48 overflow-y-auto whitespace-pre-line text-xs">{a.research.notes}</p>
            <ul className="space-y-0.5 text-xs">
              {a.research.sources.map((s) => <li key={s.url}><a href={s.url} target="_blank" rel="noopener noreferrer nofollow" className="text-accent underline-offset-2 hover:underline">{s.title}</a></li>)}
            </ul>
            <p className="text-xs text-muted">{t("studio.ground.used")}</p>
          </div>
        )}
      </section>
    </Card>
  );
}
