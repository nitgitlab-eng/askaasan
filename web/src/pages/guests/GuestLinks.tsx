import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, Copy, Download, Link2, Pencil, Plus, QrCode, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { confirmDialog } from "@/lib/dialog";
import { TimeBars } from "@/components/charts";
import { Button, Card, Field, Segmented, Toggle } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { downloadFile } from "@/lib/download";
import { copyText, expiryFromDays, guests, validSlug, type GuestLink, type LinkInput } from "@/lib/guests";

import { CampaignsTab } from "./Campaigns";
import { Modal, QrPreview } from "./shared";

function StateBadge({ state }: { state: GuestLink["state"] }) {
  const { t } = useTranslation();
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", state === "ok" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800")}>
      {t(`guest.state.${state}`)}
    </span>
  );
}

function Kpi({ label, value }: { label: string; value: ReactNode }) {
  return <div className="rounded-xl bg-surface-2 p-3"><p className="text-xs text-muted">{label}</p><p className="font-display text-xl font-extrabold tabular-nums">{value}</p></div>;
}

function StatsPanel({ link }: { link: GuestLink }) {
  const { t, i18n } = useTranslation();
  const { data: s } = useQuery({ queryKey: ["guest-stats", link.id], queryFn: () => guests.stats(link.id) });
  if (!s) return <p className="text-muted">{t("common.loading")}</p>;
  const fmt = (d: string) => new Date(d).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short" });
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Kpi label={t("guest.stats.opens")} value={s.opens} />
        <Kpi label={t("guest.stats.starts")} value={s.starts} />
        <Kpi label={t("guest.stats.completions")} value={s.completions} />
        <Kpi label={t("guest.stats.emails")} value={s.emails} />
        <Kpi label={t("guest.stats.signups")} value={s.signups} />
        <Kpi label={t("guest.stats.conversion")} value={s.conversion === null ? "—" : `${Math.round(s.conversion * 100)}%`} />
      </div>
      <TimeBars title={t("guest.stats.daily")} valueLabel={t("guest.stats.starts")} data={s.daily.map((d) => ({ label: fmt(d.day), value: d.starts }))} />
      <Button variant="outline" onClick={() => void downloadFile(guests.csvUrl(link.id), `guest-${link.slug}.csv`)}><Download className="h-4 w-4" /> {t("guest.exportCsv")}</Button>
    </div>
  );
}

const EXPIRY = [0, 1, 7, 30, 90];

function LinkDialog({ link, defaults, onClose }: { link: GuestLink | null; defaults: { org?: string; course?: number }; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: targets } = useQuery({ queryKey: ["guest-targets"], queryFn: guests.targets });
  const [f, setF] = useState<LinkInput>(() => link ? {
    label: link.label, slug: link.slug, target_kind: link.target_kind, course_id: link.course?.id ?? null, scenario_id: link.scenario?.id ?? null,
    max_uses: link.max_uses, active: link.active, collect_email: link.collect_email, org: link.org,
  } : { label: "", target_kind: "course", course_id: defaults.course ?? null, scenario_id: null, max_uses: null, active: true, collect_email: false, org: defaults.org ?? null });
  const [days, setDays] = useState<number | null>(null); // null = keep the current expiry when editing
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (p: Partial<LinkInput>) => setF((x) => ({ ...x, ...p }));

  async function save() {
    setErr("");
    if (!f.label.trim()) return setErr(t("guest.errors.label"));
    if (f.slug && !validSlug(f.slug)) return setErr(t("guest.errors.slug"));
    const body: Partial<LinkInput> = { ...f, slug: f.slug || undefined, org: f.org || "" };
    if (days !== null) body.expires_at = expiryFromDays(days);
    setBusy(true);
    try {
      if (link) await guests.update(link.id, body);
      else await guests.create(body as LinkInput);
      await qc.invalidateQueries({ queryKey: ["guest-links"] });
      onClose();
    } catch (e) {
      const code = e instanceof ApiError ? String(e.data?.code ?? "") : "";
      setErr(code === "slug_taken" ? t("guest.errors.slugTaken") : code === "bad_course" || code === "bad_scenario" ? t("guest.errors.target") : t("guest.error"));
    } finally {
      setBusy(false);
    }
  }

  const sel = "w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5";
  return (
    <Modal title={link ? t("guest.editLink") : t("guest.newLink")} onClose={onClose}>
      <div className="space-y-3">
        <Field label={t("guest.label")} value={f.label} maxLength={120} onChange={(e) => set({ label: e.target.value })} />
        <Segmented label={t("guest.targetKind")} value={f.target_kind} onChange={(v) => set({ target_kind: v })}
          options={[{ value: "course", label: t("guest.course") }, { value: "roleplay", label: t("guest.roleplay") }]} />
        {f.target_kind === "course" ? (
          <label className="block space-y-1"><span className="text-sm font-medium">{t("guest.course")}</span>
            <select className={sel} value={f.course_id ?? ""} onChange={(e) => set({ course_id: Number(e.target.value) || null })}>
              <option value="">{t("guest.pick")}</option>
              {targets?.courses.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
            </select>
            {targets && !targets.courses.length && <span className="text-xs text-muted">{t("guest.noCourses")}</span>}
          </label>
        ) : (
          <label className="block space-y-1"><span className="text-sm font-medium">{t("guest.roleplay")}</span>
            <select className={sel} value={f.scenario_id ?? ""} onChange={(e) => set({ scenario_id: Number(e.target.value) || null })}>
              <option value="">{t("guest.pick")}</option>
              {targets?.scenarios.map((s) => <option key={s.id} value={s.id}>{s.emoji} {s.title}</option>)}
            </select>
          </label>
        )}
        {link && <p className="text-xs text-muted">{t("guest.retargetHint")}</p>}
        <Field label={t("guest.slug")} value={f.slug ?? ""} placeholder={t("guest.slugAuto")} maxLength={48} onChange={(e) => set({ slug: e.target.value.toLowerCase() })} />
        <Field label={t("guest.maxUses")} type="number" min={1} value={f.max_uses ?? ""} placeholder={t("guest.unlimited")}
          onChange={(e) => set({ max_uses: e.target.value ? Math.max(1, Number(e.target.value)) : null })} />
        <div className="space-y-1">
          <span className="text-sm font-medium">{t("guest.expiry")}</span>
          <Segmented label={t("guest.expiry")} value={days ?? -1} onChange={(v) => setDays(v === -1 ? null : v)}
            options={[...(link ? [{ value: -1, label: link.expires_at ? new Date(link.expires_at).toLocaleDateString() : t("guest.never") }] : []),
              ...EXPIRY.map((d) => ({ value: d, label: d ? t("guest.days", { count: d }) : t("guest.never") }))]} />
        </div>
        <Toggle label={t("guest.active")} checked={!!f.active} onChange={(v) => set({ active: v })} />
        <Toggle label={t("guest.collectEmail")} checked={!!f.collect_email} onChange={(v) => set({ collect_email: v })} />
        {!!targets?.orgs.length && (
          <label className="block space-y-1"><span className="text-sm font-medium">{t("guest.org")}</span>
            <select className={sel} value={f.org ?? ""} onChange={(e) => set({ org: e.target.value || null })}>
              <option value="">{t("guest.noOrg")}</option>
              {targets.orgs.map((o) => <option key={o.slug} value={o.slug}>{o.name}</option>)}
            </select>
          </label>
        )}
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        <Button className="w-full" loading={busy} onClick={save}>{t("guest.save")}</Button>
      </div>
    </Modal>
  );
}

function LinksTab({ org, course }: { org?: string; course?: number }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data, error } = useQuery({ queryKey: ["guest-links", org, course], queryFn: () => guests.links({ org, course }) });
  const [editing, setEditing] = useState<GuestLink | "new" | null>(null);
  const [panel, setPanel] = useState<{ link: GuestLink; kind: "qr" | "stats" } | null>(null);
  const [copied, setCopied] = useState<number | null>(null);
  if (error) return <Card className="text-muted">{error instanceof ApiError && error.status === 403 ? t("guest.noAccess") : t("guest.error")}</Card>;
  return (
    <div className="space-y-3">
      <div className="flex justify-end"><Button onClick={() => setEditing("new")}><Plus className="h-4 w-4" /> {t("guest.newLink")}</Button></div>
      {data && !data.length && <Card className="text-center text-muted">{t("guest.empty")}</Card>}
      {data?.map((l) => (
        <Card key={l.id} className="space-y-2 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="flex items-center gap-2 font-semibold"><Link2 className="h-4 w-4 shrink-0 text-accent" /> <span className="truncate">{l.label}</span> <StateBadge state={l.state} /></p>
              <p className="truncate text-sm text-muted">{l.target_kind === "course" ? `📘 ${l.course?.title ?? "—"}` : `🎭 ${l.scenario?.title ?? "—"}`}</p>
            </div>
            <p className="text-sm tabular-nums text-muted">{t("guest.usesOf", { n: l.uses, max: l.max_uses ?? "∞" })} · {t("guest.opensN", { count: l.opens })}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <code className="max-w-full truncate rounded-lg bg-surface-2 px-2 py-1 text-xs">{l.url}</code>
            <Button variant="ghost" className="px-2 py-1 text-sm" onClick={() => { copyText(l.url); setCopied(l.id); }}><Copy className="h-4 w-4" /> {copied === l.id ? t("guest.copied") : t("guest.copy")}</Button>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" className="py-1.5 text-sm" onClick={() => setPanel({ link: l, kind: "qr" })}><QrCode className="h-4 w-4" /> {t("guest.qr")}</Button>
            <Button variant="outline" className="py-1.5 text-sm" onClick={() => setPanel({ link: l, kind: "stats" })}><BarChart3 className="h-4 w-4" /> {t("guest.statsBtn")}</Button>
            <Button variant="outline" className="py-1.5 text-sm" onClick={() => setEditing(l)}><Pencil className="h-4 w-4" /> {t("guest.edit")}</Button>
            <Button variant="ghost" className="py-1.5 text-sm text-bad" onClick={async () => {
              if (!(await confirmDialog(t("guest.confirmDelete"), { danger: true }))) return;
              await guests.remove(l.id);
              void qc.invalidateQueries({ queryKey: ["guest-links"] });
            }}><Trash2 className="h-4 w-4" /> {t("guest.delete")}</Button>
          </div>
        </Card>
      ))}
      {editing && <LinkDialog link={editing === "new" ? null : editing} defaults={{ org, course }} onClose={() => setEditing(null)} />}
      {panel && (
        <Modal title={panel.kind === "qr" ? t("guest.qrTitle", { label: panel.link.label }) : t("guest.statsTitle", { label: panel.link.label })} onClose={() => setPanel(null)}>
          {panel.kind === "qr" ? <QrPreview linkId={panel.link.id} slug={panel.link.slug} /> : <StatsPanel link={panel.link} />}
        </Modal>
      )}
    </div>
  );
}

/** Creator hub: guest links for courses / role-plays, and guest campaigns for org managers. */
export default function GuestLinksPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const org = params.get("org") || undefined;
  const course = Number(params.get("course")) || undefined;
  const tab = params.get("tab") === "campaigns" ? "campaigns" : "links";
  const { data: targets } = useQuery({ queryKey: ["guest-targets"], queryFn: guests.targets, retry: false });
  const campaignOrg = org ?? targets?.orgs[0]?.slug;
  return (
    <div className="mx-auto max-w-4xl space-y-5 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("guest.title")}</h1>
        <p className="text-muted">{t("guest.sub")}</p>
      </header>
      {!!targets?.orgs.length && (
        <Segmented label={t("guest.title")} value={tab} onChange={(v) => { const p = new URLSearchParams(params); p.set("tab", v); setParams(p, { replace: true }); }}
          options={[{ value: "links", label: t("guest.tabLinks") }, { value: "campaigns", label: t("guest.tabCampaigns") }]} />
      )}
      {tab === "links" || !campaignOrg ? <LinksTab org={org} course={course} /> : (
        <>
          {targets && targets.orgs.length > 1 && (
            <select aria-label={t("guest.org")} className="rounded-xl border-2 border-line bg-surface px-3 py-2" value={campaignOrg}
              onChange={(e) => { const p = new URLSearchParams(params); p.set("org", e.target.value); setParams(p, { replace: true }); }}>
              {targets.orgs.map((o) => <option key={o.slug} value={o.slug}>{o.name}</option>)}
            </select>
          )}
          <CampaignsTab org={campaignOrg} />
        </>
      )}
    </div>
  );
}
