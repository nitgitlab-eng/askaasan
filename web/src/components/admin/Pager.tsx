import { ChevronLeft, ChevronRight, Download } from "lucide-react";
import { useTranslation } from "react-i18next";

import { downloadFile } from "@/lib/download";

/** "Page 2 of 7 · 312 results" with prev/next, and a CSV export of the same filtered list. */
export function Pager({ page, pages, count, onPage, csvUrl, csvName }: {
  page: number;
  pages: number;
  count: number;
  onPage: (p: number) => void;
  csvUrl?: string;
  csvName?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
      <span className="text-muted">{t("admin.pager.results", { count })}</span>
      <div className="flex items-center gap-2">
        <button type="button" aria-label={t("admin.pager.prev")} disabled={page <= 1} onClick={() => onPage(page - 1)} className="rounded-lg border border-line p-1 disabled:opacity-40"><ChevronLeft className="h-4 w-4" /></button>
        <span className="tabular-nums">{t("admin.pager.page", { page, pages })}</span>
        <button type="button" aria-label={t("admin.pager.next")} disabled={page >= pages} onClick={() => onPage(page + 1)} className="rounded-lg border border-line p-1 disabled:opacity-40"><ChevronRight className="h-4 w-4" /></button>
        {csvUrl && (
          <button type="button" onClick={() => void downloadFile(csvUrl, csvName ?? "export.csv")} className="ml-2 flex items-center gap-1 rounded-lg border border-line px-2 py-1 font-semibold hover:border-accent">
            <Download className="h-4 w-4" /> {t("admin.pager.csv")}
          </button>
        )}
      </div>
    </div>
  );
}
