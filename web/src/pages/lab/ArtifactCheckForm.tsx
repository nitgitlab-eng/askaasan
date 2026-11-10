import { Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ArtifactItem } from "@/activities/lxArtifact";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Src = Record<string, any>;
const input = "w-full rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent";
const KINDS: ArtifactItem["kind"][] = ["heading", "phrase", "link", "images"];

/** Author form for "publish & check": what the learner's live page must contain (checked server-side). */
export function ArtifactCheckForm({ src, setSrc }: { src: Src; setSrc: (s: Src) => void }) {
  const { t } = useTranslation();
  const checks = (src.checks ?? []) as ArtifactItem[];
  const setCheck = (i: number, patch: Partial<ArtifactItem>) => setSrc({ ...src, checks: checks.map((c, k) => (k === i ? { ...c, ...patch } : c)) });
  return (
    <div className="space-y-3">
      <label className="block space-y-1 text-sm font-medium">{t("lx.lab.steps")}
        <textarea className={input} rows={3} value={(src.steps ?? []).join("\n")}
          onChange={(e) => setSrc({ ...src, steps: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) })} />
      </label>
      <p className="text-sm font-semibold">{t("lx.lab.checksTitle")}</p>
      {checks.map((c, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2">
          <select className="rounded-xl border-2 border-line bg-surface px-2 py-2" value={c.kind} aria-label={t("lx.lab.kind")}
            onChange={(e) => setCheck(i, { kind: e.target.value as ArtifactItem["kind"] })}>
            {KINDS.map((k) => <option key={k} value={k}>{t(`lx.lab.kinds.${k}`)}</option>)}
          </select>
          {c.kind !== "images" && (
            <input className={`${input} min-w-0 flex-1`} value={c.value} maxLength={200} placeholder={t("lx.lab.value")} aria-label={t("lx.lab.value")}
              onChange={(e) => setCheck(i, { value: e.target.value })} />
          )}
          {(c.kind === "link" || c.kind === "images") && (
            <input type="number" min={1} max={50} className={`${input} w-24`} value={c.min_count} aria-label={t("lx.lab.count")}
              onChange={(e) => setCheck(i, { min_count: Math.max(1, Math.min(50, Number(e.target.value) || 1)) })} />
          )}
          <button type="button" onClick={() => setSrc({ ...src, checks: checks.filter((_, k) => k !== i) })} aria-label={t("lx.lab.remove")}>
            <Trash2 className="h-4 w-4 text-muted" />
          </button>
        </div>
      ))}
      {checks.length < 12 && (
        <button type="button" className="flex items-center gap-1 text-sm font-semibold text-accent"
          onClick={() => setSrc({ ...src, checks: [...checks, { kind: "phrase", value: "", min_count: 1 }] })}>
          <Plus className="h-4 w-4" /> {t("lx.lab.addCheck")}
        </button>
      )}
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={src.show_checklist !== false} onChange={(e) => setSrc({ ...src, show_checklist: e.target.checked })} /> {t("lx.lab.showChecklist")}
      </label>
    </div>
  );
}
