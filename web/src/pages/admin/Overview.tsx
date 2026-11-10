import { useQuery, useQueryClient } from "@tanstack/react-query";
import { downloadFile } from "@/lib/download";
import { studio } from "@/lib/studio";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { HBars, TimeBars } from "@/components/charts";
import { Card } from "@/components/ui";
import { api } from "@/lib/api";
import { rupees } from "@/lib/billing";
import { cn } from "@/lib/cn";

type Pt = { day: string; value: number };
interface Overview {
  days: number;
  users: { total: number; new: number; verified: number; minors: number; tamil_ui: number; creators: number; series: Pt[] };
  learning: { active_7d: number; active_window: number; active_series: Pt[]; lessons_completed: number; lessons_series: Pt[]; courses_created: number; mentor_messages: number; roleplays: number; live_classes: number; live_minutes: number; orgs: number };
  money: { live_all: number; live_window: number; test_all: number; test_window: number; paying_now: number; series: Pt[] };
  ai: {
    calls: number; input_tokens: number; output_tokens: number; cost_inr: number; cost_complete: boolean; series: Pt[];
    by_model: { provider: string; model: string; calls: number; tin: number; tout: number; cost_inr: number | null }[];
    by_task: { task: string; calls: number; tokens: number }[];
    top_users: { email: string; calls: number; tokens: number }[];
    voice_minutes: number; tts_chars: number; vision_snapshots: number; images: number;
  };
  platform?: {
    workshops: { enrolments: number; enrolments_window: number; revenue_paise: number; refunds_due: number };
    certificates: { total: number; window: number; by_kind: Record<string, number> };
    orgs: { by_kind: Record<string, number>; suspended: number; paying: number; seats_paid: number; seats_used: number };
    subscriptions: { active: number; mrr_paise: number; churned_window: number };
    family?: { groups: number; members: number; mrr_paise: number };
    refunds: { count_window: number; paise_window: number };
  };
}
interface Price { provider: string; model: string; input_per_m: number | null; output_per_m: number | null }

const fmt = (n: number) => n.toLocaleString("en-IN");
const day = (d: string) => new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
const Kpi = ({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) => (
  <Card className="p-4"><p className="text-xs text-muted">{label}</p><p className="font-display text-2xl font-extrabold tabular-nums">{value}</p>{sub && <p className="text-xs text-muted">{sub}</p>}</Card>
);
const TASKS = ["tutor", "author", "grade", "suggest", "onboarding", "vision", "adaptive_interview", "adaptive_graph"];
const ORG_KINDS = ["school", "college", "coaching", "company"];

function Prices() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["admin-prices"], queryFn: () => api<Price[]>("/api/admin/model-prices/") });
  const [msg, setMsg] = useState("");
  async function save(p: Price, input: string, output: string) {
    await api("/api/admin/model-prices/", { method: "PUT", json: { provider: p.provider, model: p.model, input_per_m: Number(input) || 0, output_per_m: Number(output) || 0 } });
    setMsg(t("admin.overview.saved", { model: p.model }));
    void qc.invalidateQueries({ queryKey: ["admin-prices"] });
    void qc.invalidateQueries({ queryKey: ["admin-overview"] });
  }
  return (
    <Card className="space-y-2">
      <h2 className="font-display text-lg font-bold">{t("admin.overview.prices")}</h2>
      <p className="text-sm text-muted">{t("admin.overview.pricesHint")}</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead className="text-left text-xs text-muted"><tr><th className="py-1">{t("admin.overview.th.model")}</th><th>{t("admin.overview.thInput")}</th><th>{t("admin.overview.thOutput")}</th><th /></tr></thead>
          <tbody>
            {data?.map((p) => (
              <PriceRow key={`${p.provider}/${p.model}/${p.input_per_m}/${p.output_per_m}`} p={p} onSave={save} />
            ))}
          </tbody>
        </table>
      </div>
      {msg && <p className="text-sm text-good">{msg}</p>}
    </Card>
  );
}
function PriceRow({ p, onSave }: { p: Price; onSave: (p: Price, i: string, o: string) => void }) {
  const { t } = useTranslation();
  const [i, setI] = useState(p.input_per_m?.toString() ?? "");
  const [o, setO] = useState(p.output_per_m?.toString() ?? "");
  const box = "w-24 rounded-lg border-2 border-line bg-surface px-2 py-1";
  return (
    <tr className="border-t border-line">
      <td className="py-1.5"><span className="text-muted">{p.provider}/</span>{p.model}</td>
      <td><input className={box} inputMode="decimal" value={i} onChange={(e) => setI(e.target.value)} aria-label={t("admin.overview.inputPrice", { model: p.model })} /></td>
      <td><input className={box} inputMode="decimal" value={o} onChange={(e) => setO(e.target.value)} aria-label={t("admin.overview.outputPrice", { model: p.model })} /></td>
      <td><button className="text-sm font-semibold text-accent" onClick={() => onSave(p, i, o)}>{t("admin.common.save")}</button></td>
    </tr>
  );
}

export default function AdminOverview() {
  const { t } = useTranslation();
  const [days, setDays] = useState(30);
  const { data: d } = useQuery({ queryKey: ["admin-overview", days], queryFn: () => api<Overview>(`/api/admin/overview/?days=${days}`) });
  const o = "admin.overview";
  const calls = (n: number) => t(`${o}.calls`, { count: n });
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-extrabold">{t(`${o}.title`)}</h1>
          <p className="text-muted">{t(`${o}.sub`)}</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => void downloadFile(`${studio.urls.adminXlsx()}?days=${days}`, "aasan-overview.xlsx")} className="rounded-xl border-2 border-line px-3 py-1 text-sm font-semibold hover:border-accent">{t(`${o}.excel`)}</button>
          <div className="flex gap-1 rounded-xl bg-surface-2 p-1 text-sm">
            {[7, 30, 90].map((n) => <button key={n} onClick={() => setDays(n)} className={cn("rounded-lg px-3 py-1 font-semibold", days === n ? "bg-surface shadow" : "text-muted")}>{t(`${o}.days`, { count: n })}</button>)}
          </div>
        </div>
      </header>
      {!d ? <p className="text-muted">{t("admin.common.loading")}</p> : (
        <>
          <section className="space-y-3">
            <h2 className="font-display text-xl font-bold">{t(`${o}.learners`)}</h2>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
              <Kpi label={t(`${o}.totalAccounts`)} value={fmt(d.users.total)} sub={t(`${o}.verified`, { n: fmt(d.users.verified) })} />
              <Kpi label={t(`${o}.newN`, { days: d.days })} value={fmt(d.users.new)} />
              <Kpi label={t(`${o}.active7`)} value={fmt(d.learning.active_7d)} sub={t(`${o}.inWindow`, { n: fmt(d.learning.active_window), days: d.days })} />
              <Kpi label={t(`${o}.under18`)} value={fmt(d.users.minors)} sub={t(`${o}.guardian`)} />
              <Kpi label={t(`${o}.tamilUi`)} value={fmt(d.users.tamil_ui)} />
              <Kpi label={t(`${o}.creatorsOrgs`)} value={`${fmt(d.users.creators)} · ${fmt(d.learning.orgs)}`} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card><TimeBars title={t(`${o}.chartSignups`)} valueLabel={t(`${o}.signups`)} data={d.users.series.map((p) => ({ label: day(p.day), value: p.value }))} /></Card>
              <Card><TimeBars title={t(`${o}.chartActive`)} valueLabel={t(`${o}.learners`)} data={d.learning.active_series.map((p) => ({ label: day(p.day), value: p.value }))} /></Card>
            </div>
          </section>

          {d.platform && (
            <section className="space-y-3">
              <h2 className="font-display text-xl font-bold">{t(`${o}.platform`)}</h2>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
                <Kpi label={t(`${o}.orgs`)} value={fmt(Object.values(d.platform.orgs.by_kind).reduce((a, b) => a + b, 0))}
                  sub={Object.entries(d.platform.orgs.by_kind).map(([k, n]) => `${n} ${ORG_KINDS.includes(k) ? t(`admin.orgs.kinds.${k}`) : k}`).join(" · ") || t(`${o}.noneYet`)} />
                <Kpi label={t(`${o}.payingOrgs`)} value={`${fmt(d.platform.orgs.paying)} · ${fmt(d.platform.orgs.seats_used)}/${fmt(d.platform.orgs.seats_paid)}`}
                  sub={d.platform.orgs.suspended ? t(`${o}.suspended`, { n: d.platform.orgs.suspended }) : t(`${o}.seatsUsedPaid`)} />
                <Kpi label={t(`${o}.subs`)} value={rupees(d.platform.subscriptions.mrr_paise)}
                  sub={t(`${o}.subsSub`, { active: fmt(d.platform.subscriptions.active), churned: fmt(d.platform.subscriptions.churned_window), days: d.days })} />
                {d.platform.family && (
                  <Kpi label={t(`${o}.family`)} value={rupees(d.platform.family.mrr_paise)}
                    sub={t(`${o}.familySub`, { groups: fmt(d.platform.family.groups), members: fmt(d.platform.family.members) })} />
                )}
                <Kpi label={t(`${o}.wsEnrol`)} value={fmt(d.platform.workshops.enrolments)}
                  sub={t(`${o}.wsSub`, { n: fmt(d.platform.workshops.enrolments_window), days: d.days, amount: rupees(d.platform.workshops.revenue_paise) })} />
                <Kpi label={t(`${o}.certs`)} value={fmt(d.platform.certificates.total)} sub={t(`${o}.inWindow`, { n: fmt(d.platform.certificates.window), days: d.days })} />
                <Kpi label={t(`${o}.refunds`, { days: d.days })} value={rupees(d.platform.refunds.paise_window)}
                  sub={`${t(`${o}.refundsN`, { count: d.platform.refunds.count_window })}${d.platform.workshops.refunds_due ? ` · ${t(`${o}.seatsDue`, { n: d.platform.workshops.refunds_due })}` : ""}`} />
              </div>
            </section>
          )}

          <section className="space-y-3">
            <h2 className="font-display text-xl font-bold">{t(`${o}.learning`, { days: d.days })}</h2>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
              <Kpi label={t(`${o}.lessonsDone`)} value={fmt(d.learning.lessons_completed)} />
              <Kpi label={t(`${o}.coursesCreated`)} value={fmt(d.learning.courses_created)} />
              <Kpi label={t(`${o}.mentorMsgs`)} value={fmt(d.learning.mentor_messages)} />
              <Kpi label={t(`${o}.roleplays`)} value={fmt(d.learning.roleplays)} />
              <Kpi label={t(`${o}.liveClasses`)} value={fmt(d.learning.live_classes)} sub={t(`${o}.min`, { n: fmt(d.learning.live_minutes) })} />
              <Kpi label={t(`${o}.aiImages`)} value={fmt(d.ai.images)} />
            </div>
            <Card><TimeBars title={t(`${o}.chartLessons`)} valueLabel={t(`${o}.lessons`)} data={d.learning.lessons_series.map((p) => ({ label: day(p.day), value: p.value }))} /></Card>
          </section>

          <section className="space-y-3">
            <h2 className="font-display text-xl font-bold">{t(`${o}.money`)}</h2>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Kpi label={t(`${o}.revenue`, { days: d.days })} value={rupees(d.money.live_window)} sub={t(`${o}.allTime`, { amount: rupees(d.money.live_all) })} />
              <Kpi label={t(`${o}.payingNow`)} value={fmt(d.money.paying_now)} />
              <Kpi label={t(`${o}.testPayments`, { days: d.days })} value={rupees(d.money.test_window)} sub={t(`${o}.notReal`)} />
              <Kpi label={t(`${o}.aiCost`, { days: d.days })} value={`₹${fmt(Math.round(d.ai.cost_inr))}`} sub={d.ai.cost_complete ? t(`${o}.fromPrices`) : t(`${o}.noPrice`)} />
            </div>
            <Card><TimeBars title={t(`${o}.chartRevenue`)} valueLabel="₹" format={(v) => rupees(v)} data={d.money.series.map((p) => ({ label: day(p.day), value: p.value }))} /></Card>
          </section>

          <section className="space-y-3">
            <h2 className="font-display text-xl font-bold">{t(`${o}.aiUsage`, { days: d.days })}</h2>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
              <Kpi label={t(`${o}.aiCalls`)} value={fmt(d.ai.calls)} />
              <Kpi label={t(`${o}.inputTokens`)} value={fmt(d.ai.input_tokens)} />
              <Kpi label={t(`${o}.outputTokens`)} value={fmt(d.ai.output_tokens)} />
              <Kpi label={t(`${o}.voice`)} value={t(`${o}.min`, { n: fmt(d.ai.voice_minutes) })} />
              <Kpi label={t(`${o}.spoken`)} value={fmt(d.ai.tts_chars)} />
              <Kpi label={t(`${o}.snapshots`)} value={fmt(d.ai.vision_snapshots)} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card><TimeBars title={t(`${o}.chartTokens`)} valueLabel={t(`${o}.tokens`)} data={d.ai.series.map((p) => ({ label: day(p.day), value: p.value }))} /></Card>
              <Card><HBars title={t(`${o}.byFeature`)} valueLabel={t(`${o}.tokens`)} format={fmt} empty={t(`${o}.noCalls`)} data={d.ai.by_task.map((x) => ({ label: TASKS.includes(x.task) ? t(`${o}.tasks.${x.task}`) : x.task, value: x.tokens, note: calls(x.calls) }))} /></Card>
            </div>
            <Card className="overflow-x-auto">
              <h3 className="mb-2 font-display text-lg font-bold">{t(`${o}.byModel`)}</h3>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[36rem] text-sm">
                  <thead className="text-left text-xs text-muted"><tr><th className="py-1">{t(`${o}.th.model`)}</th><th>{t(`${o}.th.calls`)}</th><th>{t(`${o}.th.input`)}</th><th>{t(`${o}.th.output`)}</th><th>{t(`${o}.th.cost`)}</th></tr></thead>
                  <tbody>{d.ai.by_model.length === 0 ? <tr><td colSpan={5} className="py-3 text-muted">{t(`${o}.noCalls`)}</td></tr> : d.ai.by_model.map((m) => (
                    <tr key={`${m.provider}/${m.model}`} className="border-t border-line tabular-nums">
                      <td className="py-1.5"><span className="text-muted">{m.provider}/</span>{m.model}</td><td>{fmt(m.calls)}</td><td>{fmt(m.tin)}</td><td>{fmt(m.tout)}</td>
                      <td>{m.cost_inr == null ? <span className="text-muted">{t(`${o}.setPrice`)}</span> : `₹${m.cost_inr.toLocaleString("en-IN")}`}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </Card>
            {d.ai.top_users.length > 0 && (
              <Card>
                <HBars title={t(`${o}.heaviest`)} valueLabel={t(`${o}.tokens`)} format={fmt} data={d.ai.top_users.map((u) => ({ label: u.email, value: u.tokens, note: calls(u.calls) }))} />
              </Card>
            )}
            <Prices />
          </section>
        </>
      )}
    </div>
  );
}
