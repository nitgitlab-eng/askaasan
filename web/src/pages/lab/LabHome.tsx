import { useQuery } from "@tanstack/react-query";
import { FilePlus2, Sparkles, Users } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { startTour, useAutoTour } from "@/components/tour/tourStore";
import { Button, Card, Segmented } from "@/components/ui";
import { lab } from "@/lib/lab";
import { cn } from "@/lib/cn";

import { ImportCard, PresetsManager, TemplatesStrip } from "./studio/HomeExtras";

export function StatusBadge({ c }: { c: { visibility: string; catalog_status: string; published_at: string | null } }) {
  const { t } = useTranslation();
  const key = !c.published_at ? "draft" : c.visibility === "catalog" ? `catalog_${c.catalog_status}` : "link";
  const tone = key === "draft" ? "bg-surface-2 text-muted" : key === "catalog_rejected" ? "bg-bad/15 text-bad" : key === "catalog_pending" ? "bg-amber-100 text-amber-700" : "bg-good/15 text-good";
  return <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-semibold", tone)}>{t(`lab.status.${key}`)}</span>;
}

export default function LabHome() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data: courses } = useQuery({ queryKey: ["lab-courses"], queryFn: lab.courses });
  const [params] = useSearchParams();
  useAutoTour("lab");
  useEffect(() => {
    if (params.get("tour")) startTour("lab");
  }, [params]);
  const [goal, setGoal] = useState("");
  const [mode, setMode] = useState<"ai" | "blank">("ai");
  const [level, setLevel] = useState("beginner");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  async function create(e: FormEvent) {
    e.preventDefault();
    if (goal.trim().length < 3) return;
    setBusy(true);
    try {
      const c = await lab.create({ goal: goal.trim(), mode, level, notes: notes.trim() });
      navigate(`/lab/${c.id}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("lab.title")}</h1>
        <p className="text-muted">{t("lab.sub")}</p>
      </header>
      <Card data-tour="lab-new">
        <form onSubmit={create} className="space-y-3">
          <h2 className="font-display text-xl font-bold">{t("lab.new")}</h2>
          <Segmented label={t("lab.mode")} value={mode} onChange={setMode}
            options={[{ value: "ai" as const, label: `✨ ${t("lab.modeAi")}` }, { value: "blank" as const, label: `📝 ${t("lab.modeBlank")}` }]} />
          <input value={goal} onChange={(e) => setGoal(e.target.value)} maxLength={300} placeholder={mode === "ai" ? t("lab.briefPlaceholder") : t("lab.titlePlaceholder")}
            className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none focus:border-accent" aria-label={t("lab.brief")} />
          {mode === "ai" && (
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} maxLength={1000} placeholder={t("lab.audiencePlaceholder")}
              className="w-full rounded-xl border-2 border-line bg-surface p-3 outline-none focus:border-accent" aria-label={t("lab.audience")} />
          )}
          <Segmented label={t("learn.level")} value={level} onChange={setLevel} options={["beginner", "intermediate", "advanced"].map((v) => ({ value: v, label: t(`learn.levels.${v}`) }))} />
          <Button type="submit" loading={busy} disabled={goal.trim().length < 3}>
            {mode === "ai" ? <Sparkles className="h-4 w-4" /> : <FilePlus2 className="h-4 w-4" />} {t("lab.create")}
          </Button>
        </form>
      </Card>
      <div data-tour="lab-templates"><TemplatesStrip /></div>
      <div className="grid gap-4 sm:grid-cols-2">
        {courses?.map((c) => (
          <Link key={c.id} to={`/lab/${c.id}`} className="group">
            <Card className="h-full space-y-2 transition group-hover:border-accent">
              <div className="flex items-start justify-between gap-2">
                <span className="text-3xl">{c.cover_emoji}</span>
                <StatusBadge c={c} />
              </div>
              <h3 className="font-display text-lg font-bold leading-tight">{c.title}</h3>
              <p className="line-clamp-2 text-sm text-muted">{c.status === "generating" ? t("learn.building") : c.description}</p>
              <p className="flex items-center gap-1 text-xs text-muted"><Users className="h-3.5 w-3.5" /> {t("lab.learners", { count: c.learners })}</p>
            </Card>
          </Link>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div data-tour="lab-import"><ImportCard /></div>
        <div data-tour="lab-presets"><PresetsManager /></div>
      </div>
    </div>
  );
}
