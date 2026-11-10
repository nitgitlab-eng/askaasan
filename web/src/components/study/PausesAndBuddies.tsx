import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Pause, Share2, Trash2, UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { addDays, isoDay, study } from "@/lib/study";

const input = "rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm";

/** Away mode: streak protected and reminders muted for a date range. */
export function PausesCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["pauses"], queryFn: study.pauses });
  const [err, setErr] = useState("");
  const [today] = useState(() => isoDay(new Date()));
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["pauses"] });
    void qc.invalidateQueries({ queryKey: ["blocks"] });
    void qc.invalidateQueries({ queryKey: ["plan"] });
  };
  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErr("");
    const f = new FormData(e.currentTarget);
    try {
      await study.addPause({ start: String(f.get("start")), end: String(f.get("end")), reason: String(f.get("reason")) });
      refresh();
    } catch (x) {
      const d = x instanceof ApiError ? x.data : null;
      setErr(d && "end" in d ? t("pause.tooLong") : t("mentor.errors.generic"));
    }
  }
  return (
    <Card className="space-y-3">
      <h2 className="flex items-center gap-2 font-display text-xl font-bold"><Pause className="h-5 w-5 text-accent" /> {t("pause.title")}</h2>
      <p className="text-sm text-muted">{t("pause.sub")}</p>
      {data?.map((p) => (
        <div key={p.id} className="flex items-center justify-between rounded-xl border border-line px-3 py-2 text-sm">
          <span>{t(`pause.reasons.${p.reason}`)} · {p.start} → {p.end} {p.active && <span className="ml-1 rounded-full bg-accent/15 px-2 py-0.5 text-xs font-semibold text-accent">{t("pause.active")}</span>}</span>
          <button onClick={async () => { await study.removePause(p.id); refresh(); }} aria-label={t("pause.end")} className="text-muted hover:text-bad"><Trash2 className="h-4 w-4" /></button>
        </div>
      ))}
      <form onSubmit={(e) => void add(e)} className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col text-xs font-medium">{t("pause.from")}<input name="start" type="date" required defaultValue={today} min={today} className={input} /></label>
        <label className="flex flex-col text-xs font-medium">{t("pause.to")}<input name="end" type="date" required defaultValue={addDays(today, 3)} min={today} className={input} /></label>
        <label className="flex flex-col text-xs font-medium">{t("pause.why")}
          <select name="reason" className={input}>{["away", "exams", "festival", "sick", "other"].map((r) => <option key={r} value={r}>{t(`pause.reasons.${r}`)}</option>)}</select>
        </label>
        <Button type="submit" variant="outline">{t("pause.add")}</Button>
      </form>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </Card>
  );
}

/** Study buddies: share a link; once accepted you see each other's week and streak. */
export function BuddiesCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["buddies"], queryFn: study.buddies });
  const [copied, setCopied] = useState<number | null>(null);
  const share = async (id: number, link: string) => {
    const text = t("buddy.shareText", { link });
    if (navigator.share) await navigator.share({ text }).catch(() => undefined);
    else {
      await navigator.clipboard.writeText(link);
      setCopied(id);
    }
  };
  return (
    <Card className="space-y-3">
      <h2 className="flex items-center gap-2 font-display text-xl font-bold"><UserPlus className="h-5 w-5 text-accent" /> {t("buddy.title")}</h2>
      <p className="text-sm text-muted">{t("buddy.sub")}</p>
      {data?.buddies.map((b) => (
        <div key={b.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line px-3 py-2 text-sm">
          <span className="font-semibold">{b.name}</span>
          <span>🔥 {b.streak}</span>
          <span className="text-muted">{t("buddy.week", { done: b.done, planned: b.planned, count: b.studied_days.length })}</span>
          {b.paused && <span className="text-xs text-muted">⏸ {t("planner.paused")}</span>}
          <button onClick={async () => { await study.removeBuddy(b.id); void qc.invalidateQueries({ queryKey: ["buddies"] }); }} aria-label={t("buddy.remove", { name: b.name })} className="ml-auto text-muted hover:text-bad"><Trash2 className="h-4 w-4" /></button>
        </div>
      ))}
      {data?.pending.map((p) => (
        <div key={p.id} className="flex items-center gap-2 rounded-xl border border-dashed border-line px-3 py-2 text-sm">
          <span className="min-w-0 flex-1 truncate text-muted">{p.link}</span>
          <button onClick={() => void share(p.id, p.link)} className="flex items-center gap-1 font-semibold text-accent">
            {copied === p.id ? <><Copy className="h-4 w-4" /> {t("buddy.copied")}</> : <><Share2 className="h-4 w-4" /> {t("buddy.share")}</>}
          </button>
        </div>
      ))}
      <Button variant="outline" onClick={async () => qc.setQueryData(["buddies"], await study.invite())}><UserPlus className="h-4 w-4" /> {t("buddy.invite")}</Button>
    </Card>
  );
}
