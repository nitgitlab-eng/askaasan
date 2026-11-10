import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, RefreshCw, Rss } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { api } from "@/lib/api";

/** A private, auto-updating calendar link (study sessions + teacher due dates). */
export function CalendarSubscribe() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const { data } = useQuery({ queryKey: ["calendar-feed"], queryFn: () => api<{ url: string }>("/api/game/calendar-feed/"), enabled: open });
  if (!open) return <Button variant="ghost" onClick={() => setOpen(true)}><Rss className="h-4 w-4" /> {t("plan.subscribe")}</Button>;
  const webcal = data?.url.replace(/^https?:/, "webcal:");
  return (
    <div className="space-y-2 rounded-2xl bg-surface-2 p-3 text-sm">
      <p className="font-semibold">{t("plan.subscribeTitle")}</p>
      <p className="text-muted">{t("plan.subscribeHint")}</p>
      {data && (
        <>
          <code className="block truncate rounded-lg bg-surface px-2 py-1 text-xs">{data.url}</code>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" className="py-1 text-sm" onClick={() => { void navigator.clipboard.writeText(data.url); setCopied(true); }}><Copy className="h-4 w-4" /> {copied ? t("game.copied") : t("plan.copyLink")}</Button>
            <a href={webcal} className="rounded-xl border-2 border-line px-3 py-1 font-semibold hover:border-accent">{t("plan.openCalendar")}</a>
            <Button variant="ghost" className="py-1 text-sm" onClick={async () => { qc.setQueryData(["calendar-feed"], await api("/api/game/calendar-feed/", { method: "POST" })); setCopied(false); }}><RefreshCw className="h-4 w-4" /> {t("plan.newLink")}</Button>
          </div>
          <p className="text-xs text-muted">{t("plan.privateLink")}</p>
        </>
      )}
    </div>
  );
}
