import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Pager } from "@/components/admin/Pager";
import { Button, Card, Toggle } from "@/components/ui";
import { date, query, type Paged } from "@/lib/admin";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { confirmDialog } from "@/lib/dialog";
import { useMe } from "@/lib/useMe";

interface Row { id: number; name: string; slug: string; kind: string; members: number; seats_paid: number; seats_used: number; workshop_seats: number; suspended: boolean; created_at: string }
interface Detail extends Row {
  name_legal: string;
  description: string;
  members_by_role: Record<string, number>;
  admins: { id: number; email: string; role: string }[];
  subscription: { plan: string | null; seats: number; starts_at: string; ends_at: string } | null;
  features: Record<string, boolean>;
  platform_features: string[];
  workshop_seats_used: number;
  branding: { brand_color: string; logo_url: string };
  dpa: { version: string; accepted_at: string | null };
  suspended_at: string | null;
  suspended_reason: string;
  certificates: number;
  sso?: { provider: string | null; enabled: boolean; enforced: boolean; hosted_domains: string[]; domains: { domain: string; verified: boolean }[] };
}
const input = "rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm";
const KINDS = ["school", "college", "coaching", "company"];

/** Schools, colleges and companies: members, seats paid vs used, features, suspension. */
export default function AdminOrgs() {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  const qs = query({ q: search, kind, filter, page });
  const { data } = useQuery({
    queryKey: ["admin-orgs", qs],
    queryFn: () => api<Paged<Row> & { by_kind: Record<string, number> }>(`/api/admin/orgs/${qs}`),
  });
  const kindName = (k: string) => (KINDS.includes(k) ? t(`admin.orgs.kinds.${k}`) : k);
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="font-display text-3xl font-extrabold">{t("admin.orgs.title")}</h1>
        {data && <p className="text-sm text-muted">{Object.entries(data.by_kind).map(([k, n]) => `${n} ${kindName(k)}`).join(" · ")}</p>}
      </div>
      <Card className="space-y-3">
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); setSearch(q.trim()); setPage(1); }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("admin.orgs.searchPh")} aria-label={t("admin.orgs.search")} className={cn(input, "w-64")} />
          <Button type="submit" variant="outline"><Search className="h-4 w-4" /> {t("admin.common.search")}</Button>
          <select aria-label={t("admin.common.kind")} value={kind} onChange={(e) => { setKind(e.target.value); setPage(1); }} className={input}>
            <option value="">{t("admin.common.allKinds")}</option>{KINDS.map((k) => <option key={k} value={k}>{kindName(k)}</option>)}
          </select>
          <select aria-label={t("admin.common.filter")} value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1); }} className={input}>
            <option value="">{t("admin.orgs.all")}</option><option value="paying">{t("admin.orgs.paying")}</option><option value="suspended">{t("admin.orgs.suspended")}</option>
          </select>
        </form>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-sm">
            <thead className="text-left text-xs text-muted"><tr><th className="py-1">{t("admin.orgs.th.name")}</th><th>{t("admin.orgs.th.kind")}</th><th>{t("admin.orgs.th.members")}</th><th>{t("admin.orgs.th.seats")}</th><th>{t("admin.orgs.th.wsSeats")}</th><th>{t("admin.orgs.th.since")}</th><th /></tr></thead>
            <tbody>{data?.results.map((o) => (
              <tr key={o.id} className="cursor-pointer border-t border-line hover:bg-surface-2" onClick={() => setOpen(o.id)}>
                <td className="py-1.5 font-medium">{o.name} <span className="text-xs text-muted">/{o.slug}</span></td><td>{kindName(o.kind)}</td>
                <td className="tabular-nums">{o.members}</td>
                <td className={cn("tabular-nums", o.seats_used > o.seats_paid && "font-semibold text-bad")}>{o.seats_used} / {o.seats_paid}</td>
                <td className="tabular-nums">{o.workshop_seats}</td><td>{date(o.created_at)}</td>
                <td>{o.suspended && <span className="rounded bg-bad/15 px-1 text-xs text-bad">{t("admin.orgs.suspendedTag")}</span>}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        {data && <Pager page={data.page} pages={data.pages} count={data.count} onPage={setPage} csvUrl={`/api/admin/orgs/${query({ q: search, kind, filter, export: "csv" })}`} csvName="aasan-organisations.csv" />}
      </Card>
      {open && <OrgDrawer id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function OrgDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const canEdit = !!me?.staff_roles?.some((r) => r === "superadmin" || r === "support");
  const [err, setErr] = useState("");
  const { data: o } = useQuery({ queryKey: ["admin-org", id], queryFn: () => api<Detail>(`/api/admin/orgs/${id}/`) });
  const patch = async (json: object) => {
    setErr("");
    try {
      qc.setQueryData(["admin-org", id], await api<Detail>(`/api/admin/orgs/${id}/`, { method: "PATCH", json }));
      void qc.invalidateQueries({ queryKey: ["admin-orgs"] });
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 403 ? t("admin.orgs.forbidden") : t("admin.common.failed"));
    }
  };
  return (
    <div role="dialog" aria-label={t("admin.orgs.dialog")} className="fixed inset-y-0 right-0 z-40 w-full max-w-lg overflow-y-auto border-l border-line bg-bg p-5 shadow-2xl">
      <button type="button" aria-label={t("admin.common.close")} onClick={onClose} className="float-right text-muted hover:text-ink"><X className="h-5 w-5" /></button>
      {!o ? <p className="text-muted">{t("admin.common.loading")}</p> : (
        <div className="space-y-4">
          <div>
            <h2 className="font-display text-2xl font-bold">{o.name}</h2>
            <p className="text-sm text-muted">{KINDS.includes(o.kind) ? t(`admin.orgs.kinds.${o.kind}`) : o.kind} · /{o.slug} · {o.name_legal}</p>
            {o.suspended_at && <p className="mt-1 rounded-lg bg-bad/10 px-2 py-1 text-sm text-bad">{t("admin.orgs.suspendedOn", { date: date(o.suspended_at) })}{o.suspended_reason && `: ${o.suspended_reason}`}</p>}
          </div>
          <Block title={t("admin.orgs.people")}>
            <p className="text-sm">{Object.entries(o.members_by_role).map(([r, n]) => `${n} ${r}`).join(" · ") || t("admin.orgs.noMembers")}</p>
            {o.admins.map((a) => <p key={a.id} className="text-sm text-muted">{a.email} ({a.role})</p>)}
          </Block>
          <Block title={t("admin.orgs.seatsBilling")}>
            <p className="text-sm">{t("admin.orgs.seatsLine", { used: o.seats_used, paid: o.seats_paid })}</p>
            <p className="text-sm">{o.subscription ? t("admin.orgs.subLine", { plan: o.subscription.plan ?? t("admin.orgs.planFallback"), seats: o.subscription.seats, date: date(o.subscription.ends_at) }) : t("admin.orgs.noSub")}</p>
            <p className="text-sm">{t("admin.orgs.certsLine", { n: o.certificates, dpa: o.dpa.version ? t("admin.orgs.dpaAccepted", { version: o.dpa.version, date: date(o.dpa.accepted_at) }) : t("admin.orgs.dpaNot") })}</p>
          </Block>
          <Block title={t("admin.orgs.features")}>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(o.features).map(([f, on]) => (
                <Toggle key={f} checked={on} onChange={(v) => canEdit && void patch({ features: { [f]: v } })} label={`${f}${o.platform_features.includes(f) ? ` ${t("admin.orgs.platformTag")}` : ""}`} />
              ))}
            </div>
          </Block>
          <Block title={t("admin.orgs.workshops")}>
            <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); void patch({ workshop_seats: Number(new FormData(e.currentTarget).get("seats")) }); }}>
              <label className="flex flex-col text-xs font-medium">{t("admin.orgs.learnersMonth")}<input name="seats" type="number" min={0} max={100000} defaultValue={o.workshop_seats} className={cn(input, "w-28")} /></label>
              <Button type="submit" variant="outline" disabled={!canEdit}>{t("admin.common.save")}</Button>
              <span className="text-xs text-muted">{t("admin.orgs.usedMonth", { n: o.workshop_seats_used })}</span>
            </form>
          </Block>
          {o.sso && (
            <Block title={t("admin.orgs.sso")}>
              <p className="text-sm">
                {o.sso.enabled ? t("admin.orgs.ssoOn", { provider: o.sso.provider ?? "" }) : t("admin.orgs.ssoOff")}
                {o.sso.enforced && ` · ${t("admin.orgs.ssoEnforced")}`}
              </p>
              {o.sso.domains.map((d) => <p key={d.domain} className="text-sm text-muted">{d.domain} · {d.verified ? t("admin.orgs.ssoVerified") : t("admin.orgs.ssoUnverified")}</p>)}
              {canEdit && o.sso.enabled && (
                <Button variant="outline" onClick={async () => { if (await confirmDialog(t("admin.orgs.ssoOffConfirm", { name: o.name }), { danger: true })) void patch({ sso_enabled: false }); }}>
                  {t("admin.orgs.ssoSwitchOff")}
                </Button>
              )}
            </Block>
          )}
          {canEdit && (
            <Block title={t("admin.orgs.access")}>
              {o.suspended_at
                ? <Button variant="outline" onClick={() => void patch({ suspended: false })}>{t("admin.orgs.lift")}</Button>
                : (
                  <form className="flex flex-wrap items-end gap-2" onSubmit={async (e) => {
                    e.preventDefault();
                    const reason = String(new FormData(e.currentTarget).get("reason") ?? "");
                    if (await confirmDialog(t("admin.orgs.suspendConfirm", { name: o.name }), { danger: true })) void patch({ suspended: true, suspended_reason: reason });
                  }}>
                    <label className="flex flex-col text-xs font-medium">{t("admin.orgs.reason")}<input name="reason" maxLength={200} className={cn(input, "w-56")} /></label>
                    <Button type="submit" variant="outline">{t("admin.orgs.suspend")}</Button>
                  </form>
                )}
            </Block>
          )}
          {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        </div>
      )}
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1 border-t border-line pt-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
      {children}
    </section>
  );
}
