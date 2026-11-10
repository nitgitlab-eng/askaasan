import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Circle, Copy, Download, Plus, Trash2, Upload } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { localeOf } from "@/i18n/languages";
import { TemplateEditor } from "@/components/certificates/TemplateEditor";
import { Button, Card, Toggle } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { billing, payForPlan, rupees } from "@/lib/billing";
import { cn } from "@/lib/cn";
import { downloadFile } from "@/lib/download";
import { media } from "@/lib/media";
import { orgs, type FieldDef, type InviteMail, type Role } from "@/lib/orgs";
import { SsoCard } from "@/components/orgs/SsoCard";
import { UnsentInvites } from "@/components/orgs/UnsentInvites";

import { SetupWithKili } from "./School";

const input = "rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm outline-none focus:border-accent";
const FEATURES = ["mentor", "live", "roleplay", "leaderboard", "shop", "external_mcp"] as const;

function CopyLink({ url }: { url: string }) {
  const { t } = useTranslation();
  const [ok, setOk] = useState(false);
  return <button onClick={() => { void navigator.clipboard.writeText(url); setOk(true); }} className="flex items-center gap-1 text-xs font-semibold text-accent"><Copy className="h-3.5 w-3.5" /> {ok ? t("game.copied") : t("game.copyLink")}</button>;
}

/** Admin setup wizard: what's left to make the org ready, with links to each step. */
export function SetupChecklist({ slug, go }: { slug: string; go: (tab: string) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["org-setup", slug], queryFn: () => orgs.setup(slug) });
  if (!data || data.complete) return null;
  const tab: Record<string, string> = { about: "settings", brand: "settings", fields: "settings", groups: "classes", invite: "members", assign: "assignments", dpa: "overview" };
  const done = data.steps.filter((s) => s.done || s.skipped).length;
  return (
    <Card className="space-y-2 border-2 border-accent/40" data-tour="setup">
      <h2 className="font-display text-lg font-bold">{t("orgx.setupTitle", { done, total: data.steps.length })}</h2>
      <ul className="grid gap-1.5 sm:grid-cols-2">
        {data.steps.map((s) => (
          <li key={s.key} className="flex items-center gap-2 text-sm">
            {s.done ? <CheckCircle2 className="h-4 w-4 text-good" /> : <Circle className="h-4 w-4 text-muted" />}
            <button onClick={() => go(tab[s.key])} className={cn("text-left", s.done || s.skipped ? "text-muted line-through" : "font-medium hover:text-accent")}>{s.key === "about" ? t("school.stepAbout") : t(`orgx.step.${s.key}`)}</button>
            {!s.done && !s.skipped && <button onClick={async () => qc.setQueryData(["org-setup", slug], await orgs.skipSetup(slug, s.key))} className="ml-auto text-xs text-muted hover:text-accent">{t("orgx.skip")}</button>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** Brand, member fields, feature switches, shared notes. */
export function SettingsTab({ slug, canAdmin }: { slug: string; canAdmin: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: s } = useQuery({ queryKey: ["org-settings", slug], queryFn: () => orgs.settings(slug) });
  const [fields, setFields] = useState<FieldDef[] | null>(null);
  const [err, setErr] = useState("");
  const [uploading, setUploading] = useState(false);
  if (!s) return <p className="text-muted">{t("common.loading")}</p>;
  const save = async (body: Parameters<typeof orgs.saveSettings>[1]) => {
    setErr("");
    try {
      qc.setQueryData(["org-settings", slug], await orgs.saveSettings(slug, body));
      void qc.invalidateQueries({ queryKey: ["org-setup", slug] });
      void qc.invalidateQueries({ queryKey: ["my-brand"] });
    } catch (e) {
      setErr(e instanceof ApiError ? JSON.stringify(e.data) : t("mentor.errors.generic"));
    }
  };
  const fl = fields ?? s.member_fields;
  return (
    <div className="space-y-4">
      {!canAdmin && <p className="text-sm text-muted">{t("orgx.adminsOnly")}</p>}
      {canAdmin && <SetupWithKili slug={slug} />}
      <Card className="space-y-2">
        <h2 className="font-display text-lg font-bold">{t("school.about")}</h2>
        <p className="text-xs text-muted">{t("school.aboutHint")}</p>
        <textarea defaultValue={s.description ?? ""} key={s.description ?? ""} disabled={!canAdmin} maxLength={1000} rows={3} aria-label={t("school.about")}
          onBlur={(e) => e.target.value !== (s.description ?? "") && void save({ description: e.target.value })} className={cn(input, "w-full")} />
      </Card>
      <Card className="space-y-3">
        <h2 className="font-display text-lg font-bold">{t("orgx.brand")}</h2>
        <div className="flex flex-wrap items-center gap-3">
          {s.logo_url ? <img src={s.logo_url} alt="" className="h-14 w-14 rounded-xl border border-line object-contain" /> : <div className="h-14 w-14 rounded-xl bg-surface-2" />}
          <label className={cn("flex cursor-pointer items-center gap-1 text-sm font-semibold text-accent", (!canAdmin || uploading) && "pointer-events-none opacity-50")}>
            <Upload className="h-4 w-4" /> {uploading ? t("studio.lecture.uploading") : t("orgx.uploadLogo")}
            <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              setUploading(true);
              try { const a = await media.upload(f, `${s.name} logo`); await save({ logo_url: a.url }); } catch { setErr(t("mentor.errors.generic")); } finally { setUploading(false); }
            }} />
          </label>
          {s.logo_url && canAdmin && <button className="text-xs text-muted" onClick={() => void save({ logo_url: "" })}>{t("lab.delete")}</button>}
        </div>
        <label className="flex flex-wrap items-center gap-2 text-sm">{t("orgx.displayName")}
          <input defaultValue={s.display_name} key={s.display_name} disabled={!canAdmin} maxLength={120} onBlur={(e) => e.target.value !== s.display_name && void save({ display_name: e.target.value })} className={input} /></label>
        <label className="flex items-center gap-2 text-sm">{t("orgx.color")}
          <input type="color" value={s.brand_color || "#f97316"} disabled={!canAdmin} onChange={(e) => void save({ brand_color: e.target.value })} className="h-9 w-14 rounded-lg border-2 border-line" /></label>
        <p className="text-xs text-muted">{t("orgx.brandHint")}</p>
      </Card>

      <Card className="space-y-2">
        <h2 className="font-display text-lg font-bold">{t("orgx.fields")}</h2>
        <p className="text-xs text-muted">{t("orgx.fieldsHint")}</p>
        {fl.map((f, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <input value={f.label} disabled={!canAdmin} onChange={(e) => setFields(fl.map((x, k) => (k === i ? { ...x, label: e.target.value, key: x.key || e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 24) || `field${i + 1}` } : x)))} placeholder={t("orgx.fieldLabel")} className={input} />
            <select value={f.type} disabled={!canAdmin} onChange={(e) => setFields(fl.map((x, k) => (k === i ? { ...x, type: e.target.value as FieldDef["type"] } : x)))} className={input}>
              <option value="text">{t("orgx.text")}</option><option value="select">{t("orgx.select")}</option>
            </select>
            {f.type === "select" && <input value={(f.options ?? []).join(", ")} disabled={!canAdmin} onChange={(e) => setFields(fl.map((x, k) => (k === i ? { ...x, options: e.target.value.split(",").map((o) => o.trim()) } : x)))} placeholder={t("orgx.optionsPh")} className={cn(input, "min-w-0 flex-1")} />}
            <select value={f.visibility ?? "hidden"} disabled={!canAdmin} aria-label={t("school.fields.visibility")} onChange={(e) => setFields(fl.map((x, k) => (k === i ? { ...x, visibility: e.target.value as FieldDef["visibility"], self_fill: e.target.value === "editable" ? x.self_fill : false } : x)))} className={input}>
              {(["editable", "readonly", "hidden"] as const).map((v) => <option key={v} value={v}>{t(`school.fields.vis.${v}`)}</option>)}
            </select>
            <label className="flex items-center gap-1 text-xs"><input type="checkbox" disabled={!canAdmin || f.visibility !== "editable"} checked={!!f.self_fill}
              onChange={(e) => setFields(fl.map((x, k) => (k === i ? { ...x, self_fill: e.target.checked } : x)))} /> {t("school.fields.selfFill")}</label>
            {canAdmin && <button onClick={() => setFields(fl.filter((_, k) => k !== i))} aria-label={t("lab.delete")}><Trash2 className="h-4 w-4 text-muted" /></button>}
          </div>
        ))}
        {canAdmin && (
          <div className="flex gap-2">
            <Button variant="outline" className="py-1.5 text-sm" disabled={fl.length >= 10} onClick={() => setFields([...fl, { key: "", label: "", type: "text" }])}><Plus className="h-4 w-4" /> {t("orgx.addField")}</Button>
            {fields && <Button className="py-1.5 text-sm" onClick={async () => { await save({ member_fields: fields.map((f) => ({ ...f, options: f.type === "select" ? (f.options ?? []).filter(Boolean) : undefined })) }); setFields(null); }}>{t("common.save")}</Button>}
          </div>
        )}
      </Card>

      <Card className="space-y-2">
        <h2 className="font-display text-lg font-bold">{t("orgx.features")}</h2>
        <p className="text-xs text-muted">{t("orgx.featuresHint")}</p>
        {FEATURES.map((k) => <Toggle key={k} label={t(`orgx.feature.${k}`)} checked={s.features[k] !== false} onChange={(v) => canAdmin && void save({ features: { ...s.features, [k]: v } })} />)}
      </Card>
      <SharedNotes slug={slug} />
      {canAdmin && (
        <section className="space-y-2">
          <h2 className="font-display text-lg font-bold">{t("orgx.certDesign")}</h2>
          <p className="text-xs text-muted">{t("orgx.certDesignHint")}</p>
          <TemplateEditor base={`/api/credentials/orgs/${slug}/templates/`} />
        </section>
      )}
      {canAdmin && <SsoCard slug={slug} />}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </div>
  );
}

function SharedNotes({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["org-docs", slug], queryFn: () => orgs.documents(slug) });
  const { data: mine } = useQuery({ queryKey: ["docs"], queryFn: () => api<{ id: number; title: string }[]>("/api/docs/") });
  const shared = new Set(data?.map((d) => d.document_id));
  return (
    <Card className="space-y-2">
      <h2 className="font-display text-lg font-bold">{t("orgx.notes")}</h2>
      <p className="text-xs text-muted">{t("orgx.notesHint")}</p>
      {data?.map((d) => (
        <div key={d.id} className="flex items-center gap-2 text-sm">
          <span className="flex-1">📄 {d.title} <span className="text-xs text-muted">· {d.shared_by}</span></span>
          <button onClick={async () => { await orgs.unshareDocument(slug, d.id); void qc.invalidateQueries({ queryKey: ["org-docs", slug] }); }} className="text-xs text-muted hover:text-bad">{t("orgx.unshare")}</button>
        </div>
      ))}
      {!!mine?.filter((m) => !shared.has(m.id)).length && (
        <select value="" onChange={async (e) => { if (e.target.value) { await orgs.shareDocument(slug, Number(e.target.value)); void qc.invalidateQueries({ queryKey: ["org-docs", slug] }); } }} className={input} aria-label={t("orgx.shareNote")}>
          <option value="">{t("orgx.shareNote")}</option>
          {mine.filter((m) => !shared.has(m.id)).map((m) => <option key={m.id} value={m.id}>{m.title}</option>)}
        </select>
      )}
    </Card>
  );
}

/** Campaigns (shareable joining links with quota/expiry + CSV invites) and referral programmes with a payout ledger. */
export function GrowthTab({ slug, canAdmin }: { slug: string; canAdmin: boolean }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data: camps } = useQuery({ queryKey: ["campaigns", slug], queryFn: () => orgs.campaigns(slug) });
  const { data: refs } = useQuery({ queryKey: ["referrals", slug], queryFn: () => orgs.referrals(slug), enabled: canAdmin });
  const { data: ledger } = useQuery({ queryKey: ["ledger", slug], queryFn: () => orgs.ledger(slug), enabled: canAdmin });
  const [csvFor, setCsvFor] = useState<number | null>(null);
  const [csv, setCsv] = useState("");
  const [msg, setMsg] = useState("");
  const [unsent, setUnsent] = useState<InviteMail | null>(null);
  const date = (d: string) => new Date(d).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short" });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["campaigns", slug] }); void qc.invalidateQueries({ queryKey: ["referrals", slug] }); void qc.invalidateQueries({ queryKey: ["ledger", slug] }); };
  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <h2 className="font-display text-lg font-bold">{t("orgx.campaigns")}</h2>
        <p className="text-xs text-muted">{t("orgx.campaignsHint")}</p>
        <form className="flex flex-wrap items-end gap-2" onSubmit={async (e) => {
          e.preventDefault();
          const form = e.currentTarget;
          const f = new FormData(form);
          await orgs.addCampaign(slug, { name: String(f.get("name")), quota: Number(f.get("quota")), expires_at: f.get("expires") ? new Date(String(f.get("expires"))).toISOString() : null });
          form.reset();
          refresh();
        }}>
          <label className="flex flex-col text-xs font-medium">{t("orgx.campaignName")}<input name="name" required maxLength={120} className={input} /></label>
          <label className="flex flex-col text-xs font-medium">{t("orgx.quota")}<input name="quota" type="number" min={1} max={5000} defaultValue={50} className={cn(input, "w-24")} /></label>
          <label className="flex flex-col text-xs font-medium">{t("orgx.expires")}<input name="expires" type="date" className={input} /></label>
          <Button type="submit" variant="outline"><Plus className="h-4 w-4" /> {t("orgx.addCampaign")}</Button>
        </form>
        {camps?.map((c) => (
          <div key={c.id} className="space-y-2 rounded-xl border border-line p-3 text-sm">
            <div className="flex flex-wrap items-center gap-3">
              <b>{c.name}</b>
              <span className="tabular-nums text-muted">{t("orgx.used", { used: c.used, quota: c.quota })}</span>
              {c.expires_at && <span className="text-xs text-muted">{t("orgx.until", { d: date(c.expires_at) })}</span>}
              <CopyLink url={c.link} />
              <button className="text-xs font-semibold text-accent" onClick={() => setCsvFor(csvFor === c.id ? null : c.id)}>{t("orgx.emailCsv")}</button>
              <span className="ml-auto"><Toggle label={t("orgx.active")} checked={c.active} onChange={async (v) => { await orgs.setCampaign(slug, c.id, { active: v }); refresh(); }} /></span>
            </div>
            {csvFor === c.id && (
              <div className="space-y-2">
                <textarea value={csv} onChange={(e) => setCsv(e.target.value)} rows={4} placeholder={t("orgx.csvPh")} className={cn(input, "w-full font-mono text-xs")} aria-label={t("orgx.emailCsv")} />
                <div className="flex items-center gap-2">
                  <Button className="py-1.5 text-sm" disabled={!csv.trim()} onClick={async () => { setUnsent(null); try { const r = await orgs.campaignEmails(slug, c.id, csv); setMsg(r.emailed === false ? "" : t("orgx.csvDone", { invited: r.invited, skipped: r.skipped })); setUnsent(r); setCsv(""); } catch (e) { setMsg(e instanceof ApiError ? String(e.data?.code) : t("mentor.errors.generic")); } }}>{t("orgx.sendInvites")}</Button>
                  <label className="cursor-pointer text-xs font-semibold text-accent">{t("orgx.csvFile")}<input type="file" accept=".csv,text/csv,text/plain" className="sr-only" onChange={async (e) => { const f = e.target.files?.[0]; if (f) setCsv(await f.text()); }} /></label>
                  {msg && <span role="status" className="text-xs">{msg}</span>}
                </div>
                <UnsentInvites mail={unsent} />
              </div>
            )}
          </div>
        ))}
      </Card>
      {canAdmin && (
        <Card className="space-y-3">
          <h2 className="font-display text-lg font-bold">{t("orgx.referrals")}</h2>
          <p className="text-xs text-muted">{t("orgx.referralsHint")}</p>
          <form className="flex flex-wrap items-end gap-2" onSubmit={async (e) => {
            e.preventDefault();
          const form = e.currentTarget;
            const f = new FormData(form);
            try {
              await orgs.addReferral(slug, { code: String(f.get("code") || "") || undefined, reward: String(f.get("reward")), reward_paise: Math.round(Number(f.get("rupees") || 0) * 100) });
              form.reset();
              refresh();
            } catch (x) { setMsg(x instanceof ApiError && x.status === 409 ? t("orgx.codeTaken") : t("mentor.errors.generic")); }
          }}>
            <label className="flex flex-col text-xs font-medium">{t("orgx.code")}<input name="code" pattern="[A-Za-z0-9_-]{4,24}" placeholder="ANU100" className={cn(input, "w-28")} /></label>
            <label className="flex flex-col text-xs font-medium">{t("orgx.reward")}<input name="reward" maxLength={160} placeholder={t("orgx.rewardPh")} className={input} /></label>
            <label className="flex flex-col text-xs font-medium">{t("orgx.payout")}<input name="rupees" type="number" min={0} step="1" defaultValue={0} className={cn(input, "w-24")} /></label>
            <Button type="submit" variant="outline"><Plus className="h-4 w-4" /> {t("orgx.addCode")}</Button>
          </form>
          {refs?.map((r) => (
            <div key={r.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line px-3 py-2 text-sm">
              <code className="font-bold">{r.code}</code>
              <span className="text-muted">{r.reward}</span>
              <span className="tabular-nums">{t("orgx.joins", { n: r.joins })}</span>
              <span className="text-xs text-muted">{t("orgx.owedPaid", { owed: rupees(r.owed_paise), paid: rupees(r.paid_paise) })}</span>
              <CopyLink url={r.link} />
              <span className="ml-auto"><Toggle label={t("orgx.active")} checked={r.active} onChange={async (v) => { await orgs.setReferral(slug, r.id, { active: v }); refresh(); }} /></span>
            </div>
          ))}
          {!!ledger?.length && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted"><tr><th className="py-1">{t("orgx.code")}</th><th>{t("org.learner")}</th><th>{t("orgx.amount")}</th><th>{t("orgx.status")}</th><th /></tr></thead>
                <tbody>
                  {ledger.map((u) => (
                    <tr key={u.id} className="border-t border-line">
                      <td className="py-1.5"><code>{u.code}</code></td><td>{u.user}</td><td className="tabular-nums">{rupees(u.amount_paise)}</td>
                      <td>{t(`orgx.ledger.${u.status}`)}</td>
                      <td className="space-x-2 text-right text-xs">
                        {u.status === "pending" && <><button className="font-semibold text-good" onClick={async () => { await orgs.setLedger(slug, u.id, "approved"); refresh(); }}>{t("orgx.approve")}</button>
                          <button className="text-muted" onClick={async () => { await orgs.setLedger(slug, u.id, "rejected"); refresh(); }}>{t("orgx.reject")}</button></>}
                        {u.status === "approved" && <button className="font-semibold text-accent" onClick={async () => { await orgs.setLedger(slug, u.id, "paid"); refresh(); }}>{t("orgx.markPaid")}</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

/** Buy seats for learners, see who holds one, prepaid codes and invoices. */
export function SeatsTab({ slug, members }: { slug: string; members: { id: number; name: string; role: Role; seat?: boolean }[] }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["org-billing", slug], queryFn: () => billing.org(slug) });
  const { data: ov } = useQuery({ queryKey: ["billing"], queryFn: billing.overview });
  const [plan, setPlan] = useState("");
  const [seats, setSeats] = useState(30);
  const [promo, setPromo] = useState("");
  const [gstin, setGstin] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const { data: q } = useQuery({ queryKey: ["seat-quote", plan, seats, promo], queryFn: () => billing.quote(plan, { org: slug, seats, promo: promo || undefined }), enabled: !!plan && seats > 0, retry: false });
  const date = (d: string) => new Date(d).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short", year: "numeric" });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["org-billing", slug] }); void qc.invalidateQueries({ queryKey: ["org-members", slug] }); };
  async function buy() {
    setBusy(true);
    setMsg("");
    try {
      const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#f97316";
      await payForPlan(plan, accent, { org: slug, seats, promo: promo || undefined, buyer_gstin: gstin || undefined });
      setMsg(t("orgx.seatsBought", { count: seats }));
      refresh();
    } catch (e) {
      const code = e instanceof ApiError ? String(e.data?.code) : (e as Error).message;
      if (code === "payment_pending") setTimeout(refresh, 15_000); // paid; seats appear once the server confirms
      if (code !== "dismissed") setMsg(t(`billing.errors.${code}`, { defaultValue: t("billing.errors.generic") }));
    } finally {
      setBusy(false);
    }
  }
  if (!data) return <p className="text-muted">{t("common.loading")}</p>;
  return (
    <div className="space-y-4">
      <Card className="space-y-2">
        <h2 className="font-display text-lg font-bold">{t("orgx.seats")}</h2>
        {data.subscription ? (
          <p className="text-sm">{t("orgx.subLine", { plan: data.subscription.plan, used: data.seats_used, count: data.seats_total, date: date(data.subscription.ends_at) })}</p>
        ) : <p className="text-sm text-muted">{t("orgx.noSeats")}</p>}
        {data.seats_total > data.seats_used && <Button variant="outline" className="py-1.5 text-sm" onClick={async () => { await billing.assignSeats(slug); refresh(); }}>{t("orgx.fillSeats")}</Button>}
      </Card>
      <Card className="space-y-3">
        <h2 className="font-display text-lg font-bold">{t("orgx.buySeats")}</h2>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col text-xs font-medium">{t("orgx.plan")}
            <select value={plan} onChange={(e) => setPlan(e.target.value)} className={input}>
              <option value="">—</option>
              {ov?.plans.filter((p) => p.price_paise > 0).map((p) => <option key={p.code} value={p.code}>{p.name} · {rupees(p.price_paise)}/{t("orgx.perSeat")}</option>)}
            </select>
          </label>
          <label className="flex flex-col text-xs font-medium">{t("orgx.seatCount")}<input type="number" min={1} max={5000} value={seats} onChange={(e) => setSeats(Number(e.target.value))} className={cn(input, "w-24")} /></label>
          <label className="flex flex-col text-xs font-medium">{t("billing.promo")}<input value={promo} onChange={(e) => setPromo(e.target.value.toUpperCase())} className={cn(input, "w-32")} /></label>
          <label className="flex flex-col text-xs font-medium">GSTIN<input value={gstin} onChange={(e) => setGstin(e.target.value.toUpperCase())} maxLength={15} placeholder={t("billing.optional")} className={cn(input, "w-44")} /></label>
        </div>
        {q && <p className="text-sm">{q.discount_paise ? <><s className="text-muted">{rupees(q.list_paise)}</s> </> : null}<b>{rupees(q.total_paise)}</b> {t("billing.inclGst")}</p>}
        <Button loading={busy} disabled={!plan || !q} onClick={() => void buy()}>{t("orgx.pay")}</Button>
        {msg && <p role="status" className="text-sm">{msg}</p>}
      </Card>
      <Card className="space-y-2">
        <h2 className="font-display text-lg font-bold">{t("orgx.whoHasSeat")}</h2>
        <ul className="divide-y divide-line">
          {members.filter((m) => m.role === "learner").map((m) => (
            <li key={m.id} className="flex items-center justify-between py-1.5 text-sm">
              <span>{m.name}</span>
              <Toggle label={t("orgx.seat")} checked={!!m.seat} onChange={async (v) => { try { await billing.setSeat(slug, m.id, v); refresh(); } catch (e) { setMsg(e instanceof ApiError && e.data?.code === "no_free_seats" ? t("orgx.noFree") : t("mentor.errors.generic")); } }} />
            </li>
          ))}
        </ul>
      </Card>
      {(data.redeem_codes.total > 0 || data.orders.length > 0) && (
        <Card className="space-y-2 text-sm">
          {data.redeem_codes.total > 0 && (
            <p className="flex items-center gap-2">{t("orgx.codes", data.redeem_codes)}
              <button className="flex items-center gap-1 font-semibold text-accent" onClick={() => void downloadFile(`/api/billing/orgs/${slug}/redeem-codes/?export=csv`, "codes.csv")}><Download className="h-4 w-4" /> CSV</button></p>
          )}
          {data.orders.map((o) => (
            <p key={o.id} className="flex items-center gap-2">{date(o.paid_at)} · {o.plan} × {o.seats} · {rupees(o.amount_paise)}
              {o.invoice && <button className="flex items-center gap-1 font-semibold text-accent" onClick={() => void downloadFile(billing.invoiceUrl(o.invoice!), "invoice.pdf")}><Download className="h-4 w-4" /> {o.invoice}</button>}</p>
          ))}
        </Card>
      )}
    </div>
  );
}
