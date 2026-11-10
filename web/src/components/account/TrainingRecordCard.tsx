import { useQuery } from "@tanstack/react-query";
import { Download, FileCheck2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { downloadFile } from "@/lib/download";
import { records } from "@/lib/records";

/** Account: the learner's own training record (what their organisations can see), with Excel / PDF downloads.
 * Hidden for learners with no records (most personal learners). */
export function TrainingRecordCard() {
  const { t, i18n } = useTranslation();
  const { data } = useQuery({ queryKey: ["my-training-record"], queryFn: records.mine });
  const [err, setErr] = useState("");
  if (!data?.length) return null;
  const day = (d: string) => new Date(d).toLocaleDateString(localeOf(i18n.language));
  const get = (fmt: "xlsx" | "pdf") => {
    setErr("");
    downloadFile(records.urls.mine(fmt), `my-training-record.${fmt}`).catch(() => setErr(t("records.failed")));
  };
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold"><FileCheck2 className="h-5 w-5 text-accent" /> {t("records.mineTitle")}</h2>
        <div className="flex gap-2">
          <Button variant="ghost" className="py-1.5 text-sm" onClick={() => get("xlsx")}><Download className="h-4 w-4" /> {t("records.excel")}</Button>
          <Button variant="ghost" className="py-1.5 text-sm" onClick={() => get("pdf")}><Download className="h-4 w-4" /> {t("records.pdf")}</Button>
        </div>
      </div>
      <p className="text-sm text-muted">{t("records.mineSub")}</p>
      <ul className="divide-y divide-line text-sm">
        {data.slice(0, 20).map((r) => (
          <li key={r.id} className="flex flex-wrap items-center gap-2 py-2">
            <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold">{t(`records.kind.${r.kind}`)}</span>
            <span className="min-w-0 flex-1 font-medium">{r.title}</span>
            <span className="text-xs text-muted">{r.org} · {t("records.completed", { date: day(r.completed_at) })}{r.score !== null ? ` · ${t("records.score", { pct: r.score })}` : ""}</span>
          </li>
        ))}
      </ul>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </Card>
  );
}
