import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { localeOf } from "@/i18n/languages";
import { Button, Card } from "@/components/ui";
import { api } from "@/lib/api";

interface View { name: string; days: number; minutes: number; active_days: number; lessons: { title: string; course: string; score: number | null; on: string }[]; lessons_count: number; streak: number; last_active: string | null; digest: boolean; consent?: "pending" | "given" | "objected" | null }

/** Read-only weekly progress for a parent/guardian (no login; link can be revoked by the learner). */
export default function GuardianPage() {
  const { t, i18n } = useTranslation();
  const { token = "" } = useParams();
  const [days, setDays] = useState(7);
  const [stopped, setStopped] = useState(false);
  const [changing, setChanging] = useState(false);
  const qc = useQueryClient();
  const { data, error } = useQuery({ queryKey: ["guardian", token, days], queryFn: () => api<View>(`/api/guardian/${token}/?days=${days}`), retry: false });
  if (error) return <main className="mx-auto max-w-xl px-4 py-16 text-center text-muted">{t("guardian.invalid")}</main>;
  if (!data) return <main className="p-8 text-muted">{t("common.loading")}</main>;
  const decide = async (agree: boolean) => {
    await api(`/api/guardian/${token}/consent/`, { method: "POST", json: { agree } });
    setChanging(false);
    await qc.invalidateQueries({ queryKey: ["guardian", token] });
  };
  const fmt = (d: string) => new Date(d).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short" });
  return (
    <main className="mx-auto max-w-2xl space-y-4 px-4 py-10">
      <header>
        <p className="text-sm text-muted">{t("guardian.kicker")}</p>
        <h1 className="font-display text-3xl font-extrabold">{t("guardian.title", { name: data.name })}</h1>
        <div className="mt-2 flex gap-2">{[7, 30].map((d) => <button key={d} onClick={() => setDays(d)} aria-pressed={days === d} className={days === d ? "rounded-full bg-accent px-3 py-1 text-sm font-semibold text-accent-ink" : "rounded-full border border-line px-3 py-1 text-sm"}>{t("progress.days", { count: d })}</button>)}</div>
      </header>
      {(data.consent === "pending" || changing) ? (
        <Card className="space-y-3 border-accent">
          <h2 className="font-display text-xl font-bold">{t("guardian.consentAsk", { name: data.name })}</h2>
          <p className="text-sm">{t("guardian.consentWhat")}</p>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void decide(true)}>{t("guardian.agree")}</Button>
            <Button variant="ghost" onClick={() => void decide(false)}>{t("guardian.disagree")}</Button>
          </div>
        </Card>
      ) : data.consent && (
        <p role="status" className="text-sm">
          {data.consent === "given" ? t("guardian.consentGiven", { name: data.name }) : t("guardian.consentRefused")}{" "}
          <button className="font-semibold text-accent underline" onClick={() => setChanging(true)}>{t("guardian.consentChange")}</button>
        </p>
      )}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[[t("guardian.minutes"), data.minutes], [t("guardian.days"), data.active_days], [t("guardian.lessons"), data.lessons_count], [t("guardian.streak"), `🔥 ${data.streak}`]].map(([k, v]) => (
          <Card key={String(k)} className="p-4"><p className="text-xs text-muted">{k}</p><p className="font-display text-2xl font-extrabold">{v}</p></Card>
        ))}
      </div>
      <Card>
        <h2 className="mb-2 font-display text-lg font-bold">{t("guardian.recent")}</h2>
        {!data.lessons.length ? <p className="text-sm text-muted">{t("guardian.none")}</p> : (
          <ul className="divide-y divide-line text-sm">
            {data.lessons.map((l, i) => <li key={i} className="flex justify-between gap-3 py-1.5"><span><b>{l.title}</b> <span className="text-muted">· {l.course}</span></span><span className="shrink-0 text-muted">{l.score !== null ? `${l.score}% · ` : ""}{fmt(l.on)}</span></li>)}
          </ul>
        )}
      </Card>
      <p className="text-xs text-muted">{t("guardian.privacy")}</p>
      {data.digest && !stopped && <Button variant="ghost" onClick={async () => { await api(`/api/guardian/${token}/stop/`, { method: "POST" }); setStopped(true); }}>{t("guardian.stop")}</Button>}
      {stopped && <p role="status" className="text-sm text-good">{t("guardian.stopped")}</p>}
    </main>
  );
}
