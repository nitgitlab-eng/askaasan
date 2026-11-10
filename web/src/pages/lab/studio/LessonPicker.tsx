import { useQuery } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { LabCourse } from "@/lib/lab";
import { studio } from "@/lib/studio";

/** Reuse a lesson (with its activities) from another of my courses or a template. */
export function LessonPicker({ sectionId, onDone }: { sectionId: number; onDone: (c: LabCourse) => void }) {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const { data } = useQuery({ queryKey: ["lesson-library", q], queryFn: () => studio.library(q) });
  const [busy, setBusy] = useState<number | null>(null);
  return (
    <div className="space-y-2 rounded-xl border-2 border-dashed border-line p-2">
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("studio.picker.search")} aria-label={t("studio.picker.search")} autoFocus
        className="w-full rounded-lg border-2 border-line bg-surface px-2 py-1 text-sm outline-none focus:border-accent" />
      <ul className="max-h-56 space-y-1 overflow-y-auto">
        {data?.map((l) => (
          <li key={l.id}>
            <button disabled={busy !== null} onClick={async () => { setBusy(l.id); try { onDone(await studio.importLesson(sectionId, l.id)); } finally { setBusy(null); } }}
              className="flex w-full items-start gap-2 rounded-lg px-2 py-1 text-left text-sm hover:bg-surface-2 disabled:opacity-50">
              <Copy className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
              <span className="min-w-0"><span className="block truncate font-medium">{l.title}</span><span className="block truncate text-xs text-muted">{l.course} · {t("studio.picker.acts", { count: l.activities })}</span></span>
            </button>
          </li>
        ))}
        {data && !data.length && <li className="px-2 text-xs text-muted">{t("studio.picker.none")}</li>}
      </ul>
    </div>
  );
}
