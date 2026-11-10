import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Info, RefreshCw, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

type Status = "ok" | "warn" | "error" | "info";
interface Item { group: string; key: string; label: string; status: Status; detail: string; link: string }
const ICON = { ok: CheckCircle2, warn: AlertTriangle, error: XCircle, info: Info };
const COLOR = { ok: "text-good", warn: "text-amber-600", error: "text-bad", info: "text-muted" };
const SEED_CMD = "python manage.py seed_demo --full";

export default function SystemCheck() {
  const { t } = useTranslation();
  const { data, refetch, isFetching } = useQuery({ queryKey: ["system-check"], queryFn: () => api<{ items: Item[]; summary: Record<Status, number> }>("/api/admin/system-check/") });
  const groups = [...new Set(data?.items.map((i) => i.group))];
  const checklist = t("admin.system.checklist", { returnObjects: true }) as string[];
  const [hintBefore, hintAfter] = t("admin.system.checklistHint", { cmd: "\u0000" }).split("\u0000");
  return (
    <div className="mx-auto max-w-4xl space-y-5 px-4 py-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-extrabold">{t("admin.system.title")}</h1>
          <p className="text-muted">{t("admin.system.sub")}</p>
        </div>
        <Button variant="outline" loading={isFetching} onClick={() => void refetch()}><RefreshCw className="h-4 w-4" /> {t("admin.system.recheck")}</Button>
      </header>
      {data && (
        <div className="flex flex-wrap gap-2 text-sm font-semibold">
          {(["error", "warn", "info", "ok"] as Status[]).map((s) => {
            const I = ICON[s];
            return <span key={s} className={cn("flex items-center gap-1 rounded-full bg-surface-2 px-3 py-1", COLOR[s])}><I className="h-4 w-4" /> {data.summary[s]} {t(`admin.system.summary.${s}`)}</span>;
          })}
        </div>
      )}
      {groups.map((g) => (
        <Card key={g} className="divide-y divide-line p-0">
          <h2 className="px-5 py-3 font-display text-lg font-bold">{g}</h2>
          {data!.items.filter((i) => i.group === g).map((i) => {
            const I = ICON[i.status];
            return (
              <div key={i.key} className="flex items-start gap-3 px-5 py-3">
                <I className={cn("mt-0.5 h-5 w-5 shrink-0", COLOR[i.status])} aria-label={i.status} />
                <div className="min-w-0 flex-1"><p className="font-medium">{i.label}</p><p className="break-words text-sm text-muted">{i.detail}</p></div>
                {i.link && i.status !== "ok" && <Link to={i.link} className="shrink-0 text-sm font-semibold text-accent">{t("admin.system.fix")}</Link>}
              </div>
            );
          })}
        </Card>
      ))}
      <Card className="space-y-2">
        <h2 className="font-display text-lg font-bold">{t("admin.system.checklistTitle")}</h2>
        <p className="text-sm text-muted">{hintBefore}<code>{SEED_CMD}</code>{hintAfter}</p>
        <ol className="list-decimal space-y-1 pl-5 text-sm">{(Array.isArray(checklist) ? checklist : []).map((c) => <li key={c}>{c}</li>)}</ol>
      </Card>
    </div>
  );
}
