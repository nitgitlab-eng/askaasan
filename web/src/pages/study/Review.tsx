import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Printer, Sparkles } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SharePanel } from "@/components/credentials/SharePanel";
import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { downloadFile } from "@/lib/download";
import { studio } from "@/lib/studio";
import { useMe } from "@/lib/useMe";

/** Quarterly learning review: AI-written from the learner's own numbers; save as PDF (print) or Excel. */
export default function ReviewPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { data } = useQuery({ queryKey: ["quarter-review"], queryFn: studio.review });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function write() {
    setBusy(true);
    setErr("");
    try {
      qc.setQueryData(["quarter-review"], await studio.writeReview());
    } catch (e) {
      setErr(e instanceof ApiError && e.data?.code === "ai_budget_exceeded" ? t("paths.budget") : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }
  if (!data) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  const r = data.review;
  const list = (title: string, items: string[]) => items.length ? (
    <section className="break-inside-avoid"><h2 className="mb-1 font-display text-lg font-bold">{title}</h2><ul className="list-disc space-y-0.5 pl-5">{items.map((x) => <li key={x}>{x}</li>)}</ul></section>
  ) : null;
  return (
    <div className="mx-auto max-w-3xl space-y-5 px-4 py-8 print:max-w-none print:p-0">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-muted">{data.quarter} · {me?.profile.display_name}</p>
          <h1 className="font-display text-3xl font-extrabold">{r?.title ?? t("review2.title")}</h1>
        </div>
        {r && (
          <div className="flex gap-2 print:hidden">
            <Button variant="outline" onClick={() => window.print()}><Printer className="h-4 w-4" /> {t("review2.pdf")}</Button>
            <Button variant="ghost" onClick={() => void downloadFile(studio.urls.reviewXlsx(), "review.xlsx")}><Download className="h-4 w-4" /> Excel</Button>
          </div>
        )}
      </header>
      {!r ? (
        <Card className="space-y-3 text-center print:hidden">
          <p>{t("review2.sub")}</p>
          <Button className="mx-auto" loading={busy} onClick={() => void write()}><Sparkles className="h-4 w-4" /> {t("review2.write")}</Button>
          {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        </Card>
      ) : (
        <Card className="space-y-4 print:border-0 print:shadow-none">
          <p className="text-[1.05rem]">{r.overview}</p>
          {data.facts && (
            <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
              {[["minutes", t("progress.timeSpent")], ["lessons", t("progress.lessonsDone")], ["active_days", t("progress.activeDays")], ["first_try_accuracy", t("progress.firstTry")]].map(([k, label]) => (
                <div key={k} className="rounded-xl bg-surface-2 p-2"><p className="text-xs text-muted">{label}</p><p className="font-display text-xl font-bold">{data.facts!.totals[k] ?? "—"}{k === "first_try_accuracy" && data.facts!.totals[k] != null ? "%" : ""}</p></div>
              ))}
            </div>
          )}
          {list(t("review2.covered"), r.covered)}
          {list(t("review2.mastered"), r.mastered)}
          {list(t("review2.growth"), r.growth)}
          {list(t("review2.next"), r.next_quarter)}
          <p className="text-xs text-muted">{t("review2.note")}</p>
        </Card>
      )}
      {r && <SharePanel src={{ source: "review" }} />}
    </div>
  );
}
