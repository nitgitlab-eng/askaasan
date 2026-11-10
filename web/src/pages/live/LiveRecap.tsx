import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { PageError } from "@/components/PageState";
import { Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { badId } from "@/lib/ids";
import type { LiveSummary } from "@/live/useLiveSocket";

import { SummaryCard } from "./Live";

interface Detail { id: number; title: string; minutes: number; started_at: string; summary: LiveSummary | Record<string, never>; turns: { role: string; text: string; saw: boolean; proactive: boolean }[] }

export default function LiveRecap() {
  const { t } = useTranslation();
  const { id } = useParams();
  const qc = useQueryClient();
  const { data, error, refetch } = useQuery({ queryKey: ["live-session", id], queryFn: () => api<Detail>(`/api/live/sessions/${id}/`), enabled: !badId(Number(id)) });
  const [busy, setBusy] = useState(false);
  if (badId(Number(id))) return <PageError notFound />;
  if (error && !data) return <PageError error={error} onRetry={() => void refetch()} />;
  if (!data) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  const has = "title" in data.summary;
  return (
    <div className="mx-auto max-w-3xl space-y-5 px-4 py-8">
      <header>
        <Link to="/live" className="text-sm text-accent">← {t("live.title")}</Link>
        <h1 className="font-display text-3xl font-extrabold">{data.title || t("live.untitled")}</h1>
        <p className="text-muted">{new Date(data.started_at).toLocaleString()} · {t("live.mins", { n: data.minutes })}</p>
      </header>
      {has ? <SummaryCard s={data.summary as LiveSummary} /> : (
        <Card className="flex items-center justify-between gap-3">
          <p className="text-muted">{t("live.noSummary")}</p>
          <Button variant="outline" loading={busy} onClick={async () => { setBusy(true); try { qc.setQueryData(["live-session", id], await api<Detail>(`/api/live/sessions/${id}/`, { method: "POST" })); } finally { setBusy(false); } }}>{t("live.makeSummary")}</Button>
        </Card>
      )}
      <Card>
        <h2 className="mb-2 font-display text-lg font-bold">{t("live.transcript")}</h2>
        <ul className="space-y-2">
          {data.turns.map((m, i) => (
            <li key={i} className={m.role === "user" ? "text-right" : ""}>
              <span className={cn("inline-block max-w-[85%] rounded-2xl px-3 py-1.5 text-left", m.role === "user" ? "bg-accent text-accent-ink" : "bg-surface-2")}>
                {m.saw && <Eye className="mr-1 inline h-3.5 w-3.5 opacity-60" aria-label={t("live.saw")} />}{m.text}
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
