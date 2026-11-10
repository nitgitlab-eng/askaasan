import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { observeSteps, type ObserveStep } from "@/lib/observeSteps";

const input = "w-full rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent";
const blank = (): ObserveStep => ({ label: "", url_pattern: "https://", text: "" });

function Form({ activityId, initial, initialOptional }: { activityId: number; initial: ObserveStep[]; initialOptional: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [steps, setSteps] = useState<ObserveStep[]>(initial);
  const [optional, setOptional] = useState(initialOptional);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [hosts, setHosts] = useState<string[]>([]);
  const set = (i: number, k: keyof ObserveStep, v: string) => setSteps(steps.map((s, j) => (j === i ? { ...s, [k]: v } : s)));

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await observeSteps.save(activityId, steps.map(({ label, url_pattern, text }) => ({ label, url_pattern, text })), optional);
      qc.setQueryData(["observe-steps", activityId], r);
      setSteps(r.steps);
      setOptional(r.optional);
      setHosts(r.hosts);
      setMsg({ ok: true, text: t("rcaSteps.saved") });
    } catch (e) {
      const detail = e instanceof ApiError ? String(e.data?.detail ?? e.data?.code ?? e.status) : t("mentor.errors.generic");
      setMsg({ ok: false, text: t("rcaSteps.error", { detail }) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      {steps.length === 0 && <p className="text-sm text-muted">{t("rcaSteps.none")}</p>}
      <ol className="space-y-2">
        {steps.map((s, i) => (
          <li key={i} className="space-y-1 rounded-xl border border-line p-2">
            <div className="flex items-center gap-2">
              <p className="flex-1 text-sm font-semibold">{t("rcaSteps.stepN", { n: i + 1 })}</p>
              <button type="button" onClick={() => setSteps(steps.filter((_, j) => j !== i))} aria-label={t("rcaSteps.remove", { n: i + 1 })}>
                <Trash2 className="h-4 w-4 text-muted" />
              </button>
            </div>
            <label className="block space-y-1 text-sm font-medium">{t("rcaSteps.label")}
              <input className={input} maxLength={120} value={s.label} onChange={(e) => set(i, "label", e.target.value)} />
            </label>
            <label className="block space-y-1 text-sm font-medium">{t("rcaSteps.pattern")}
              <input className={input} maxLength={300} dir="ltr" inputMode="url" placeholder="https://docs.google.com/spreadsheets/*" value={s.url_pattern}
                onChange={(e) => set(i, "url_pattern", e.target.value)} />
            </label>
            <label className="block space-y-1 text-sm font-medium">{t("rcaSteps.text")}
              <input className={input} maxLength={80} value={s.text} onChange={(e) => set(i, "text", e.target.value)} />
            </label>
          </li>
        ))}
      </ol>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={optional} onChange={(e) => setOptional(e.target.checked)} /> {t("rcaStepsOpt.optional")}</label>
      <div className="flex flex-wrap gap-2">
        {steps.length < 8 && (
          <Button variant="ghost" className="py-1 text-sm" onClick={() => setSteps([...steps, blank()])}><Plus className="h-4 w-4" /> {t("rcaSteps.add")}</Button>
        )}
        <Button variant="outline" className="py-1 text-sm" loading={busy} onClick={() => void save()}>{t("rcaSteps.save")}</Button>
      </div>
      {msg && <p role={msg.ok ? "status" : "alert"} className={msg.ok ? "text-sm text-good" : "text-sm text-bad"}>{msg.text}</p>}
      {hosts.length > 0 && <p className="text-xs text-muted">{t("rcaSteps.hosts", { hosts: hosts.join(", ") })}</p>}
    </div>
  );
}

/** Author-side editor for a browser task's live-observation steps (saved separately from the activity source). */
export function ObserveStepsEditor({ activityId }: { activityId: number }) {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["observe-steps", activityId], queryFn: () => observeSteps.get(activityId) });
  return (
    <details className="rounded-xl border border-line bg-surface p-3">
      <summary className="cursor-pointer text-sm font-semibold">{t("rcaSteps.title")}</summary>
      <div className="mt-2 space-y-2">
        <p className="text-xs text-muted">{t("rcaSteps.help")}</p>
        {data ? <Form activityId={activityId} initial={data.steps} initialOptional={data.optional} /> : <p className="text-sm text-muted">{t("common.loading")}</p>}
      </div>
    </details>
  );
}
