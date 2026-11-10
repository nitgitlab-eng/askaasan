import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Button, Card, Segmented } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { roleplay, type Scenario } from "@/lib/roleplay";
import { Kili } from "@/mascot/Kili";
import { mascot } from "@/mascot/store";
import { AssignedBadge, AssignedScenarios } from "@/pages/orgs/teach/MyAssignments";
import { useScenarioAssignments } from "@/pages/orgs/teach/useMyAssignments";

const DIFF_COLOR = { easy: "bg-good/15 text-good", medium: "bg-amber-100 text-amber-700", hard: "bg-bad/15 text-bad" };

export default function RolePlayStudio() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data: scenarios } = useQuery({ queryKey: ["scenarios"], queryFn: roleplay.scenarios });
  const { data: history } = useQuery({ queryKey: ["rp-sessions"], queryFn: roleplay.sessions });
  const [goal, setGoal] = useState("");
  const [difficulty, setDifficulty] = useState("medium");
  const [busy, setBusy] = useState<number | "gen" | null>(null);
  const [error, setError] = useState("");
  const assignedBy = useScenarioAssignments();
  const [params] = useSearchParams();
  const [now] = useState(() => Date.now());

  async function start(s: Scenario, assignmentId?: number) {
    setBusy(s.id);
    try {
      const session = await roleplay.start(s.id, assignmentId);
      navigate(`/roleplay/${session.id}`);
    } finally {
      setBusy(null);
    }
  }
  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy("gen");
    setError("");
    mascot.react("thinking", 0);
    try {
      const s = await roleplay.generate(goal.trim(), difficulty);
      await start(s);
    } catch (err) {
      mascot.react("hmm");
      setError(err instanceof ApiError && err.data?.code === "not_allowed" ? t("rp.notAllowed") : t("mentor.errors.generic"));
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("rp.title")}</h1>
        <p className="text-muted">{t("rp.sub")}</p>
      </header>
      <Card className="flex flex-col gap-4 bg-gradient-to-br from-accent/15 to-surface sm:flex-row sm:items-center">
        <Kili mood={busy === "gen" ? "thinking" : "wave"} size={100} />
        <form onSubmit={create} className="flex-1 space-y-3">
          <h2 className="font-display text-xl font-bold">{t("rp.custom")}</h2>
          <input value={goal} onChange={(e) => setGoal(e.target.value)} minLength={5} maxLength={300} placeholder={t("rp.customPlaceholder")}
            className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none focus:border-accent" aria-label={t("rp.custom")} />
          <div className="flex flex-wrap items-center gap-3">
            <Segmented label={t("rp.difficulty")} value={difficulty} onChange={setDifficulty} options={(["easy", "medium", "hard"] as const).map((v) => ({ value: v, label: t(`rp.diff.${v}`) }))} />
            <Button type="submit" loading={busy === "gen"} disabled={goal.trim().length < 5}><Sparkles className="h-4 w-4" /> {t("rp.build")}</Button>
          </div>
          {error && <p role="alert" className="text-sm text-bad">{error}</p>}
        </form>
      </Card>
      <AssignedScenarios busy={typeof busy === "number" ? busy : null} focus={Number(params.get("assignment")) || undefined}
        onStart={(id, aid) => void start({ id } as Scenario, aid)} />
      {(["custom", "library"] as const).map((src) => {
        const list = scenarios?.filter((x) => x.source === src) ?? [];
        if (!list.length) return null;
        return (
          <section key={src} className="space-y-3">
            <h2 className="font-display text-xl font-bold">{src === "custom" ? t("rp.yours") : t("rp.library")}</h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {list.map((s) => (
          <Card key={s.id} className="flex flex-col gap-2">
            <div className="flex items-start justify-between">
              <span className="text-4xl">{s.emoji}</span>
              <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-semibold", DIFF_COLOR[s.difficulty])}>{t(`rp.diff.${s.difficulty}`)}</span>
            </div>
            <h3 className="font-display text-lg font-bold leading-tight">{s.title}</h3>
            {assignedBy.get(s.id) && <AssignedBadge a={assignedBy.get(s.id)!} now={now} />}
            <p className="flex-1 text-sm text-muted">{s.summary}</p>
            <p className="text-xs text-muted">🎭 {s.character.name} · {s.competencies.map((c) => c.name).join(", ")}</p>
            <Button className="mt-1" loading={busy === s.id} onClick={() => start(s)}>{t("rp.start")}</Button>
          </Card>
        ))}
            </div>
          </section>
        );
      })}
      {!!history?.length && (
        <Card>
          <h2 className="mb-2 font-display text-xl font-bold">{t("rp.history")}</h2>
          <ul className="divide-y divide-line">
            {history.slice(0, 8).map((h) => (
              <li key={h.id}>
                <Link to={`/roleplay/${h.id}`} className="flex items-center gap-3 py-2 hover:text-accent">
                  <span className="text-xl">{h.scenario.emoji}</span>
                  <span className="flex-1 truncate">{h.scenario.title}</span>
                  {h.result ? <b>{h.result.overall}</b> : <span className="text-xs text-muted">{t("rp.inProgress")}</span>}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
