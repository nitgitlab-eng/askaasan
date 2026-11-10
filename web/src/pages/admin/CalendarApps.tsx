import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, CheckCircle2, Copy, ExternalLink, Save, XCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import i18n from "@/i18n";
import { confirmDialog } from "@/lib/dialog";
import { Button, Card, Toggle } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";

interface CalApp {
  provider: "google" | "microsoft"; label: string; client_id: string; secret: string | null; tenant: string; enabled: boolean; ready: boolean;
  redirect_uri: string; scopes: string[]; console: string; env_vars: string[]; connections: number; updated_at: string | null;
}

const input = "w-full rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent";
const errText = (e: unknown) => (e instanceof ApiError ? String(e.data?.detail ?? e.data?.code ?? JSON.stringify(e.data)) : i18n.t("mentor.errors.generic"));

function AppCard({ app }: { app: CalApp }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [clientId, setClientId] = useState(app.client_id);
  const [secret, setSecret] = useState("");
  const [tenant, setTenant] = useState(app.tenant);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);

  async function patch(body: object) {
    setBusy(true);
    setResult(null);
    try {
      const out = await api<CalApp>(`/api/admin/calendar-apps/${app.provider}/`, { method: "PATCH", json: body });
      qc.setQueryData<{ apps: CalApp[] }>(["admin-calendar-apps"], (d) => d && { ...d, apps: d.apps.map((a) => (a.provider === out.provider ? out : a)) });
      return true;
    } catch (e) {
      setResult({ ok: false, detail: errText(e) });
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    const body: Record<string, string> = {};
    if (clientId.trim() !== app.client_id) body.client_id = clientId.trim();
    if (secret) body.client_secret = secret;
    if (app.provider === "microsoft" && tenant.trim() !== app.tenant) body.tenant = tenant.trim() === "common" ? "" : tenant.trim();
    if (await patch(body)) {
      setSecret("");
      setResult({ ok: true, detail: t("adminCal.saved") });
    }
  }

  return (
    <Card className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <h2 className="flex items-center gap-2 font-display text-xl font-bold"><CalendarDays className="h-5 w-5" /> {app.label}</h2>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted">{t("adminCal.connected", { n: app.connections })}</span>
          <span className={cn("rounded-full px-2.5 py-1 text-xs font-bold", app.ready ? "bg-good/15 text-good" : "bg-surface-2 text-muted")}>{app.ready ? t("adminCal.ready") : t("adminCal.notReady")}</span>
        </div>
      </header>
      <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
        {(t(`adminCal.steps.${app.provider}`, { returnObjects: true }) as string[]).map((s) => <li key={s}>{s}</li>)}
      </ol>
      <a href={app.console} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-sm font-semibold text-accent">{t("adminCal.openConsole")} <ExternalLink className="h-3.5 w-3.5" /></a>
      <div className="space-y-2 rounded-xl bg-surface-2 p-3 text-sm">
        <p className="font-semibold">{t("adminCal.redirectTitle")}</p>
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded bg-surface px-2 py-1">{app.redirect_uri}</code>
          <Button variant="ghost" className="py-1 text-sm" aria-label={t("admin.copyRedirect")} onClick={() => void navigator.clipboard.writeText(app.redirect_uri)}><Copy className="h-4 w-4" /></Button>
        </div>
        <p className="font-semibold">{t("adminCal.scopes")}</p>
        <p>{app.scopes.map((s) => <code key={s} className="mr-2 inline-block max-w-full break-all rounded bg-surface px-1.5 py-0.5">{s}</code>)}</p>
        <p className="text-xs text-muted">{t("adminCal.uriNote")}</p>
      </div>
      <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium">{t("adminCal.clientId")}
          <input value={clientId} onChange={(e) => setClientId(e.target.value)} className={cn(input, "mt-1 font-mono")} autoComplete="off" />
        </label>
        <label className="text-sm font-medium">{t("adminCal.clientSecret")}
          <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={app.secret ?? t("adminCal.pasteSecret")} className={cn(input, "mt-1 font-mono")} autoComplete="new-password" />
        </label>
        {app.provider === "microsoft" && (
          <label className="text-sm font-medium">{t("adminCal.tenant")} <span className="font-normal text-muted">{t("adminCal.tenantHint")}</span>
            <input value={tenant} onChange={(e) => setTenant(e.target.value)} className={cn(input, "mt-1 font-mono")} autoComplete="off" />
          </label>
        )}
        <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
          <Button type="submit" loading={busy}><Save className="h-4 w-4" /> {t("common.save")}</Button>
          {app.secret && <Button type="button" variant="outline" disabled={busy} onClick={async () => { if (await confirmDialog(t("admin.clearSecretConfirm"), { danger: true })) void patch({ client_secret: "" }); }}>{t("admin.clearSecret")}</Button>}
          <Toggle checked={app.enabled} onChange={(v) => void patch({ enabled: v })} label={t("adminCal.offer")} />
        </div>
      </form>
      <p className="text-xs text-muted">{t("adminCal.secretsNote")} <code>{app.env_vars.join(", ")}</code>.</p>
      {result && <p role="status" className={cn("flex items-center gap-2 text-sm", result.ok ? "text-good" : "text-bad")}>{result.ok ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />} {result.detail}</p>}
    </Card>
  );
}

export default function AdminCalendarApps() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["admin-calendar-apps"], queryFn: () => api<{ apps: CalApp[] }>("/api/admin/calendar-apps/") });
  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("adminCal.title")}</h1>
        <p className="text-muted">{t("adminCal.sub")}</p>
      </header>
      {data?.apps.map((a) => <AppCard key={`${a.provider}:${a.client_id}:${a.secret}:${a.tenant}`} app={a} />)}
    </div>
  );
}
