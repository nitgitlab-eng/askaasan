import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { Card, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { gameKey, useGame } from "@/lib/game";

type Scope = { scope: "global" | "org" | "class"; name: string; org?: string; class?: number };

interface Board {
  scope?: Scope["scope"];
  name?: string;
  scopes?: Scope[];
  ends_in_days: number;
  rows: { rank: number; name: string; xp: number; me: boolean; league: { name: string; icon: string } }[];
  me: { xp: number; league: { name: string; icon: string }; rank?: number | null };
  my_rank?: number | null;
}

const keyOf = (s: Pick<Scope, "scope" | "org" | "class">) => (s.scope === "class" ? `class:${s.class}` : s.scope === "org" ? `org:${s.org}` : "global");

export default function LeaderboardPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: g } = useGame();
  const [params, setParams] = useSearchParams();
  const scope = (params.get("scope") as Scope["scope"]) || "global";
  const org = params.get("org") ?? "";
  const cls = params.get("class") ?? "";
  const qs = scope === "org" ? `?scope=org&org=${encodeURIComponent(org)}` : scope === "class" ? `?scope=class&class=${encodeURIComponent(cls)}` : "";
  const { data, isError } = useQuery({ queryKey: ["leaderboard", scope, org, cls], queryFn: () => api<Board>(`/api/game/leaderboard/${qs}`) });
  const { data: global } = useQuery({ queryKey: ["leaderboard", "global", "", ""], queryFn: () => api<Board>("/api/game/leaderboard/"), enabled: isError && scope !== "global" });
  const toggle = useMutation({
    mutationFn: (v: boolean) => api("/api/game/settings/", { method: "PATCH", json: { show_on_leaderboard: v } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: gameKey });
      void qc.invalidateQueries({ queryKey: ["leaderboard"] });
    },
  });
  const medal = ["🥇", "🥈", "🥉"];
  const scopes = data?.scopes ?? global?.scopes ?? [];
  const current = keyOf({ scope, org, class: Number(cls) });
  const pick = (s: Scope) =>
    setParams(s.scope === "org" ? { scope: "org", org: s.org ?? "" } : s.scope === "class" ? { scope: "class", class: String(s.class) } : {}, { replace: true });
  const rankShown = data?.my_rank && !data.rows.some((r) => r.me);
  return (
    <div className="mx-auto max-w-2xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("game.leaderboard")}</h1>
        <p className="text-muted">{t("game.weekEnds", { count: data?.ends_in_days ?? 7 })}</p>
      </header>
      {scopes.length > 1 && (
        <div role="tablist" aria-label={t("game.scopes.label")} className="flex flex-wrap gap-2">
          {scopes.map((s) => {
            const k = keyOf(s);
            return (
              <button key={k} role="tab" aria-selected={k === current} onClick={() => pick(s)}
                className={cn("rounded-full border-2 px-3 py-1 text-sm", k === current ? "border-accent bg-accent/10 font-semibold" : "border-line hover:border-accent")}>
                {s.scope === "global" ? t("game.scopes.global") : s.scope === "org" ? t("game.scopes.org", { name: s.name }) : t("game.scopes.class", { name: s.name })}
              </button>
            );
          })}
        </div>
      )}
      {isError ? (
        <Card><p className="text-muted">{t("game.scopes.unavailable")}</p></Card>
      ) : (
        <>
          <Card className="flex items-center gap-4 bg-gradient-to-br from-accent/15 to-surface">
            <span className="text-5xl">{data?.me.league.icon}</span>
            <div>
              <p className="font-display text-2xl font-bold">{t(`game.leagues.${data?.me.league.name ?? "bronze"}`)}</p>
              <p className="text-sm text-muted">{t("game.weekXp", { n: data?.me.xp ?? 0 })}</p>
              {rankShown && <p className="text-sm font-semibold">{t("game.scopes.myRank", { n: data?.my_rank })}</p>}
            </div>
          </Card>
          <Card className="divide-y divide-line p-0">
            {data?.rows.length ? data.rows.map((r) => (
              <div key={r.rank} className={cn("flex items-center gap-3 px-5 py-3", r.me && "bg-accent/10")}>
                <span className="w-8 text-center font-display text-lg font-bold">{medal[r.rank - 1] ?? r.rank}</span>
                <span className="flex-1 font-semibold">{r.name}{r.me && ` (${t("game.you")})`}</span>
                <span className="text-sm">{r.league.icon}</span>
                <span className="w-20 text-right font-bold">{r.xp} XP</span>
              </div>
            )) : <p className="p-5 text-muted">{t("game.boardEmpty")}</p>}
          </Card>
        </>
      )}
      <Card><Toggle label={t("game.showMe")} checked={g?.show_on_leaderboard ?? true} onChange={(v) => toggle.mutate(v)} /></Card>
    </div>
  );
}
