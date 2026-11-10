import { Download, FileCheck2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { downloadFile } from "@/lib/download";
import { records, type RecordFormat } from "@/lib/records";

const FORMATS: { fmt: RecordFormat; key: string; file: string }[] = [
  { fmt: "csv", key: "records.csv", file: "training-records.csv" },
  { fmt: "xlsx", key: "records.excel", file: "training-records.xlsx" },
  { fmt: "pdf", key: "records.pdf", file: "training-records.pdf" },
];

/** Cockpit: download the organisation's compliance training records (a teacher gets their classes only). */
export function RecordsExport({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const [err, setErr] = useState("");
  return (
    <Card className="flex flex-wrap items-center gap-3">
      <FileCheck2 className="h-5 w-5 text-accent" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{t("records.title")}</p>
        <p className="text-xs text-muted">{t("records.sub")}</p>
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label={t("records.exportLabel")}>
        {FORMATS.map(({ fmt, key, file }) => (
          <Button key={fmt} variant="ghost" className="py-1.5 text-sm"
            onClick={() => { setErr(""); downloadFile(records.urls.org(slug, fmt), file).catch(() => setErr(t("records.failed"))); }}>
            <Download className="h-4 w-4" /> {t(key)}
          </Button>
        ))}
      </div>
      {err && <p role="alert" className="w-full text-sm text-bad">{err}</p>}
    </Card>
  );
}
