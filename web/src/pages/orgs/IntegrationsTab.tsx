import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Send, Trash2, Webhook as WebhookIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card, Toggle } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { confirmDialog } from "@/lib/dialog";
import { integrations, type ApiScope, type Delivery, type HookEvent, type Webhook } from "@/lib/integrations";

const SCOPES: ApiScope[] = ["read:progress", "read:members", "write:members"];
const EVENTS: HookEvent[] = ["member.joined", "assignment.completed", "course.completed", "certificate.issued", "workshop.passed"];
const scopeKey = (s: string) => `intg.scope.${s.replace(":", "_")}`;
const eventKey = (e: string) => `intg.event.${e.replace(".", "_")}`;

function useDay() {
  const { i18n } = useTranslation();
  return (d: string | null) => (d ? new Date(d).toLocaleString(localeOf(i18n.language), { dateStyle: "medium", timeStyle: "short" }) : "—");
}

/** A secret or key shown exactly once, with a copy button. */
function ShownOnce({ label, value, onDone }: { label: string; value: string; onDone: () => void }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  return (
    <div role="status" className="space-y-2 rounded-xl border-2 border-amber-400 bg-amber-50 p-3 text-sm text-amber-950">
      <p className="font-semibold">{label}</p>
      <div className="flex flex-wrap items-center gap-2">
        <code className="min-w-0 flex-1 break-all rounded-lg bg-white px-2 py-1 font-mono text-xs" data-testid="shown-once">{value}</code>
        <Button variant="outline" className="py-1 text-sm" onClick={() => { void navigator.clipboard?.writeText(value); setCopied(true); }}>
          <Copy className="h-4 w-4" /> {copied ? t("intg.copied") : t("intg.copy")}
        </Button>
        <Button variant="ghost" className="py-1 text-sm" onClick={onDone}>{t("intg.done")}</Button>
      </div>
      <p className="text-xs">{t("intg.onceNote")}</p>
    </div>
  );
}

function KeysCard({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const day = useDay();
  const { data } = useQuery({ queryKey: ["intg-keys", slug], queryFn: () => integrations.keys(slug) });
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<ApiScope[]>(["read:progress"]);
  const [raw, setRaw] = useState("");
  const [err, setErr] = useState("");
  async function create(e: FormEvent) {
    e.preventDefault();
    setErr("");
    try {
      const k = await integrations.createKey(slug, name.trim(), scopes);
      setRaw(k.key ?? "");
      setName("");
      void qc.invalidateQueries({ queryKey: ["intg-keys", slug] });
    } catch (x) {
      setErr(x instanceof ApiError && x.data?.code === "too_many_keys" ? t("intg.keys.tooMany") : t("mentor.errors.generic"));
    }
  }
  async function revoke(id: number) {
    if (!(await confirmDialog(t("intg.keys.revokeConfirm")))) return;
    await integrations.revokeKey(slug, id);
    void qc.invalidateQueries({ queryKey: ["intg-keys", slug] });
  }
  return (
    <Card className="space-y-3">
      <h2 className="flex items-center gap-2 font-display text-lg font-bold"><KeyRound className="h-5 w-5 text-accent" /> {t("intg.keys.title")}</h2>
      <p className="text-sm text-muted">{t("intg.keys.sub")}</p>
      {raw && <ShownOnce label={t("intg.keys.newKey")} value={raw} onDone={() => setRaw("")} />}
      <ul className="divide-y divide-line text-sm">
        {data?.keys.length === 0 && <li className="py-2 text-muted">{t("intg.keys.none")}</li>}
        {data?.keys.map((k) => (
          <li key={k.id} className={cn("flex flex-wrap items-center gap-2 py-2", k.revoked_at && "opacity-60")}>
            <span className="font-semibold">{k.name}</span>
            <code className="rounded bg-surface-2 px-1.5 font-mono text-xs">{k.prefix}…</code>
            {k.scopes.map((s) => <span key={s} className="rounded-full bg-surface-2 px-2 py-0.5 text-xs">{t(scopeKey(s))}</span>)}
            <span className="ml-auto text-xs text-muted">{k.revoked_at ? t("intg.keys.revoked") : t("intg.keys.lastUsed", { when: day(k.last_used_at) })}</span>
            {!k.revoked_at && <Button variant="ghost" className="py-1 text-sm text-bad" onClick={() => void revoke(k.id)}>{t("intg.keys.revoke")}</Button>}
          </li>
        ))}
      </ul>
      <form onSubmit={(e) => void create(e)} className="space-y-2 rounded-xl border border-line p-3">
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder={t("intg.keys.namePh")} aria-label={t("intg.keys.name")}
          className="w-full rounded-lg border-2 border-line bg-surface px-3 py-1.5 text-sm" />
        <fieldset className="flex flex-wrap gap-3 text-sm">
          <legend className="sr-only">{t("intg.keys.scopes")}</legend>
          {SCOPES.map((s) => (
            <label key={s} className="flex items-center gap-1.5">
              <input type="checkbox" checked={scopes.includes(s)} onChange={(e) => setScopes(e.target.checked ? [...scopes, s] : scopes.filter((x) => x !== s))} />
              {t(scopeKey(s))}
            </label>
          ))}
        </fieldset>
        <Button type="submit" disabled={!name.trim() || !scopes.length}>{t("intg.keys.create")}</Button>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      </form>
      <p className="text-xs text-muted">{t("intg.keys.howto", { base: `${location.origin}/api/v1/orgs/${slug}/` })}</p>
    </Card>
  );
}

function Deliveries({ slug, hook }: { slug: string; hook: Webhook }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const day = useDay();
  const key = ["intg-deliveries", slug, hook.id];
  const { data } = useQuery({ queryKey: key, queryFn: () => integrations.deliveries(slug, hook.id) });
  if (!data) return <p className="text-sm text-muted">{t("common.loading")}</p>;
  if (!data.results.length) return <p className="text-sm text-muted">{t("intg.hooks.noDeliveries")}</p>;
  const tone = (d: Delivery) => (d.status === "ok" ? "text-good" : d.status === "dead" ? "text-bad" : "text-amber-700");
  return (
    <ul className="divide-y divide-line rounded-lg border border-line text-xs">
      {data.results.map((d) => (
        <li key={d.id} className="flex flex-wrap items-center gap-2 px-3 py-1.5">
          <span className="font-mono">#{d.id}</span>
          <span>{t(eventKey(d.event), { defaultValue: d.event })}</span>
          <span className={cn("font-semibold", tone(d))}>{t(`intg.status.${d.status}`)}</span>
          <span className="text-muted">{t("intg.hooks.attempt", { n: d.attempt })}{d.response_status ? ` · HTTP ${d.response_status}` : ""}{d.last_error ? ` · ${d.last_error}` : ""}</span>
          <span className="ml-auto text-muted">{day(d.created_at)}</span>
          {(d.status === "dead" || d.status === "failed") && d.event !== "ping" && (
            <Button variant="ghost" className="py-0.5 text-xs" onClick={async () => { await integrations.redeliver(slug, hook.id, d.id); void qc.invalidateQueries({ queryKey: key }); }}>
              {t("intg.hooks.redeliver")}
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}

function WebhooksCard({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["intg-hooks", slug], queryFn: () => integrations.webhooks(slug) });
  const [url, setUrl] = useState("");
  const [evs, setEvs] = useState<HookEvent[]>(["course.completed"]);
  const [secret, setSecret] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const refresh = () => void qc.invalidateQueries({ queryKey: ["intg-hooks", slug] });
  const why = (x: unknown) => {
    if (x instanceof ApiError && x.data?.code === "bad_url") return t("intg.hooks.badUrl", { reason: t(`intg.reason.${String(x.data.reason)}`, { defaultValue: String(x.data.reason) }) });
    if (x instanceof ApiError && x.data?.code === "too_many_webhooks") return t("intg.hooks.tooMany");
    if (x instanceof ApiError && x.status === 429) return t("intg.hooks.testLimit");
    return t("mentor.errors.generic");
  };
  async function create(e: FormEvent) {
    e.preventDefault();
    setErr("");
    try {
      const w = await integrations.createWebhook(slug, url.trim(), evs);
      setSecret(w.secret ?? "");
      setUrl("");
      refresh();
    } catch (x) {
      setErr(why(x));
    }
  }
  async function act(fn: () => Promise<unknown>) {
    setErr("");
    setMsg("");
    try {
      await fn();
    } catch (x) {
      setErr(why(x));
    }
    refresh();
  }
  return (
    <Card className="space-y-3">
      <h2 className="flex items-center gap-2 font-display text-lg font-bold"><WebhookIcon className="h-5 w-5 text-accent" /> {t("intg.hooks.title")}</h2>
      <p className="text-sm text-muted">{t("intg.hooks.sub")}</p>
      {secret && <ShownOnce label={t("intg.hooks.newSecret")} value={secret} onDone={() => setSecret("")} />}
      {data?.webhooks.length === 0 && <p className="text-sm text-muted">{t("intg.hooks.none")}</p>}
      {data?.webhooks.map((w) => (
        <div key={w.id} className="space-y-2 rounded-xl border border-line p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 break-all font-mono text-xs">{w.url}</code>
            <Toggle checked={w.active} label={t("intg.hooks.active")} onChange={(v) => void act(() => integrations.updateWebhook(slug, w.id, { active: v }))} />
          </div>
          <div className="flex flex-wrap gap-1">{w.events.map((e) => <span key={e} className="rounded-full bg-surface-2 px-2 py-0.5 text-xs">{t(eventKey(e))}</span>)}</div>
          {!w.active && w.disabled_reason && <p className="text-xs text-bad">{t("intg.hooks.autoDisabled")}</p>}
          {w.last_delivery && <p className="text-xs text-muted">{t("intg.hooks.last", { status: t(`intg.status.${w.last_delivery.status}`) })}</p>}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" className="py-1 text-sm" onClick={() => void act(async () => { const d = await integrations.test(slug, w.id); setMsg(d.status === "ok" ? t("intg.hooks.testOk") : t("intg.hooks.testFailed", { error: d.last_error || d.response_status || "" })); })}>
              <Send className="h-4 w-4" /> {t("intg.hooks.test")}
            </Button>
            <Button variant="ghost" className="py-1 text-sm" aria-expanded={open === w.id} onClick={() => setOpen(open === w.id ? null : w.id)}>{t("intg.hooks.deliveries")}</Button>
            <Button variant="ghost" className="py-1 text-sm" onClick={() => void act(async () => { if (await confirmDialog(t("intg.hooks.rotateConfirm"))) setSecret((await integrations.rotateSecret(slug, w.id)).secret ?? ""); })}>{t("intg.hooks.rotate")}</Button>
            <Button variant="ghost" className="py-1 text-sm text-bad" onClick={() => void act(async () => { if (await confirmDialog(t("intg.hooks.deleteConfirm"))) await integrations.deleteWebhook(slug, w.id); })}>
              <Trash2 className="h-4 w-4" /> {t("intg.hooks.delete")}
            </Button>
          </div>
          {open === w.id && <Deliveries slug={slug} hook={w} />}
        </div>
      ))}
      {msg && <p role="status" className="text-sm text-muted">{msg}</p>}
      <form onSubmit={(e) => void create(e)} className="space-y-2 rounded-xl border border-line p-3">
        <input value={url} onChange={(e) => setUrl(e.target.value)} maxLength={500} type="url" placeholder="https://hr.example.com/aasan-webhook" aria-label={t("intg.hooks.url")}
          className="w-full rounded-lg border-2 border-line bg-surface px-3 py-1.5 text-sm" />
        <fieldset className="flex flex-wrap gap-3 text-sm">
          <legend className="sr-only">{t("intg.hooks.events")}</legend>
          {EVENTS.map((e) => (
            <label key={e} className="flex items-center gap-1.5">
              <input type="checkbox" checked={evs.includes(e)} onChange={(x) => setEvs(x.target.checked ? [...evs, e] : evs.filter((y) => y !== e))} />
              {t(eventKey(e))}
            </label>
          ))}
        </fieldset>
        <Button type="submit" disabled={!url.trim().startsWith("https://") || !evs.length}>{t("intg.hooks.create")}</Button>
      </form>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      <details className="text-sm">
        <summary className="cursor-pointer font-semibold">{t("intg.hooks.verifyTitle")}</summary>
        <div className="mt-2 space-y-2 text-muted">
          <p>{t("intg.hooks.verifyText")}</p>
          <pre className="overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-xs text-ink">{`expected = hmac_sha256(secret, timestamp + "." + raw_body)
header   = "X-Aasan-Signature: sha256=" + hex(expected)
# reject if the signatures differ or X-Aasan-Timestamp is older than 5 minutes`}</pre>
          <p>{t("intg.hooks.verifyNote")}</p>
        </div>
      </details>
    </Card>
  );
}

/** Cockpit → Integrations (owners and admins): API keys for /api/v1/ and outbound webhooks. */
export default function IntegrationsTab({ slug }: { slug: string }) {
  return (
    <div className="space-y-4">
      <KeysCard slug={slug} />
      <WebhooksCard slug={slug} />
    </div>
  );
}
