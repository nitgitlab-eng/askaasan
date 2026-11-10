import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Mail, Save, Send, XCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card, Toggle } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";

interface MailCfg { enabled: boolean; host: string; port: number; security: "tls" | "ssl" | "none"; username: string; password: string | null; from_email: string; from_name: string; ready: boolean; fallback: string }

/** Names are product names (not translated); `note` is the key under admin.email.presets. */
const PRESETS = [
  { name: "Gmail / Google Workspace", host: "smtp.gmail.com", port: 587, security: "tls", note: "gmail" },
  { name: "Zoho Mail (India)", host: "smtp.zoho.in", port: 587, security: "tls", note: "zoho" },
  { name: "Amazon SES (Mumbai)", host: "email-smtp.ap-south-1.amazonaws.com", port: 587, security: "tls", note: "ses" },
  { name: "Brevo", host: "smtp-relay.brevo.com", port: 587, security: "tls", note: "brevo" },
] as const;
const input = "mt-1 w-full rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent";

function Form({ cfg }: { cfg: MailCfg }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [d, setD] = useState({ ...cfg, password: "" });
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);
  async function save(e?: FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      const body: Record<string, unknown> = { enabled: d.enabled, host: d.host.trim(), port: Number(d.port), security: d.security, username: d.username.trim(), from_email: d.from_email.trim(), from_name: d.from_name };
      if (d.password) body.password = d.password;
      qc.setQueryData(["admin-mail"], await api<MailCfg>("/api/admin/mail/", { method: "PATCH", json: body }));
      setResult({ ok: true, detail: t("admin.email.saved") });
    } catch (x) {
      setResult({ ok: false, detail: x instanceof ApiError ? JSON.stringify(x.data) : t("admin.common.saveFailed") });
    } finally {
      setBusy(false);
    }
  }
  async function test() {
    setBusy(true);
    setResult(null);
    try {
      setResult(await api("/api/admin/mail/test/", { method: "POST", json: { to } }));
    } catch (x) {
      setResult({ ok: false, detail: x instanceof ApiError ? String(x.data?.detail ?? x.data?.code) : t("admin.email.testFailed") });
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Card className="space-y-2">
        <p className="text-sm font-semibold">{t("admin.email.quick")}</p>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button key={p.name} type="button" onClick={() => { setD({ ...d, host: p.host, port: p.port, security: p.security }); setResult({ ok: true, detail: t(`admin.email.presets.${p.note}`) }); }}
              className="rounded-full border-2 border-line px-3 py-1 text-sm hover:border-accent">{p.name}</button>
          ))}
        </div>
      </Card>
      <Card>
        <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm font-medium sm:col-span-2">{t("admin.email.server")}<input className={input} value={d.host} onChange={(e) => setD({ ...d, host: e.target.value })} placeholder="smtp.example.com" /></label>
          <label className="text-sm font-medium">{t("admin.email.port")}<input className={input} inputMode="numeric" value={d.port} onChange={(e) => setD({ ...d, port: Number(e.target.value) || 587 })} /></label>
          <label className="text-sm font-medium">{t("admin.email.security")}
            <select className={input} value={d.security} onChange={(e) => setD({ ...d, security: e.target.value as MailCfg["security"] })}>
              <option value="tls">{t("admin.email.tls")}</option><option value="ssl">{t("admin.email.ssl")}</option><option value="none">{t("admin.email.none")}</option>
            </select>
          </label>
          <label className="text-sm font-medium">{t("admin.email.username")}<input className={input} value={d.username} onChange={(e) => setD({ ...d, username: e.target.value })} autoComplete="off" /></label>
          <label className="text-sm font-medium">{t("admin.email.password")} {cfg.password && <span className="font-normal text-muted">{t("admin.email.savedPw", { masked: cfg.password })}</span>}
            <input className={input} type="password" value={d.password} onChange={(e) => setD({ ...d, password: e.target.value })} placeholder={cfg.password ? t("admin.passwordKeepHint") : ""} title={cfg.password ? t("admin.passwordKeepHint") : undefined} autoComplete="new-password" />
          </label>
          <label className="text-sm font-medium">{t("admin.email.fromEmail")}<input className={input} type="email" value={d.from_email} onChange={(e) => setD({ ...d, from_email: e.target.value })} placeholder="no-reply@yourdomain.in" /></label>
          <label className="text-sm font-medium">{t("admin.email.fromName")}<input className={input} value={d.from_name} onChange={(e) => setD({ ...d, from_name: e.target.value })} /></label>
          <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
            <Toggle checked={d.enabled} onChange={(v) => setD({ ...d, enabled: v })} label={t("admin.email.use")} />
            <Button type="submit" loading={busy}><Save className="h-4 w-4" /> {t("admin.common.save")}</Button>
          </div>
        </form>
      </Card>
      <Card className="space-y-2">
        <p className="font-semibold">{t("admin.email.testTitle")}</p>
        <div className="flex flex-wrap gap-2">
          <input className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2" type="email" value={to} onChange={(e) => setTo(e.target.value)} placeholder={t("admin.email.testPh")} aria-label={t("admin.email.testRecipient")} />
          <Button variant="outline" disabled={busy || !cfg.ready} onClick={test}><Send className="h-4 w-4" /> {t("admin.email.sendTest")}</Button>
        </div>
        {result && <p role="status" className={cn("flex items-start gap-2 text-sm", result.ok ? "text-good" : "text-bad")}>{result.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}<span className="break-words">{result.detail}</span></p>}
      </Card>
    </>
  );
}

export default function AdminEmail() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["admin-mail"], queryFn: () => api<MailCfg>("/api/admin/mail/") });
  return (
    <div className="mx-auto max-w-3xl space-y-5 px-4 py-8">
      <header>
        <h1 className="flex items-center gap-2 font-display text-3xl font-extrabold"><Mail className="h-7 w-7" /> {t("admin.email.title")}</h1>
        <p className="text-muted">{t("admin.email.sub")}</p>
        {data && <p className={cn("mt-2 inline-block rounded-full px-3 py-1 text-xs font-bold", data.ready ? "bg-good/15 text-good" : "bg-amber-100 text-amber-800")}>{data.ready ? t("admin.email.ready") : t("admin.email.notSet", { fallback: data.fallback })}</p>}
      </header>
      {data && <Form key={`${data.host}:${data.password}:${data.from_email}`} cfg={data} />}
    </div>
  );
}
