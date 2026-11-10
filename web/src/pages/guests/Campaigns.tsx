import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Copy, Mail, Plus, QrCode, RefreshCw, Send, Trash2, Upload } from "lucide-react";
import { useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";

import { confirmDialog } from "@/lib/dialog";
import { Button, Card, Field } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { copyText, guests, parseProspects, type Campaign, type Prospect } from "@/lib/guests";
import { localeOf } from "@/i18n/languages";

import { Modal, QrPreview } from "./shared";

const LANGS = ["en", "ta", "tanglish", "hi", "te", "kn", "ml", "bn", "mr", "gu"];

function errorText(t: (k: string, o?: Record<string, unknown>) => string, e: unknown): string {
  const code = e instanceof ApiError ? String(e.data?.code ?? "") : "";
  const known = ["daily_limit", "unsubscribed", "already_sent", "not_ready", "send_failed", "no_prospects", "too_many_prospects", "plan_limit", "busy"];
  if (code === "account_limit" || code === "global_limit") return t(`guestSafe.${code}`);
  if (code === "email_not_configured") return t("mailSetup.notReady");
  return known.includes(code) ? t(`guest.campaign.err.${code}`) : t("guest.error");
}

function NewCampaign({ org, onDone }: { org: string; onDone: (c: Campaign) => void }) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [topic, setTopic] = useState("");
  const [language, setLanguage] = useState("en");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const preview = parseProspects(text);

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 100_000) return setErr(t("guest.campaign.fileTooBig"));
    setText(await f.text());
  }

  async function submit() {
    setErr("");
    if (!name.trim() || !topic.trim()) return setErr(t("guest.campaign.needNameTopic"));
    if (!preview.rows.length) return setErr(t("guest.campaign.err.no_prospects"));
    setBusy(true);
    try {
      onDone(await guests.createCampaign(org, { name, topic, language, prospects: text }));
    } catch (e) {
      setErr(errorText(t, e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-3">
      <h2 className="font-display text-lg font-bold">{t("guest.campaign.new")}</h2>
      <Field label={t("guest.campaign.name")} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
      <Field label={t("guest.campaign.topic")} value={topic} maxLength={200} placeholder={t("guest.campaign.topicHint")} onChange={(e) => setTopic(e.target.value)} />
      <label className="block space-y-1"><span className="text-sm font-medium">{t("guest.campaign.language")}</span>
        <select className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2.5" value={language} onChange={(e) => setLanguage(e.target.value)}>
          {LANGS.map((l) => <option key={l} value={l}>{t(`guest.campaign.langs.${l}`)}</option>)}
        </select>
      </label>
      <label className="block space-y-1">
        <span className="text-sm font-medium">{t("guest.campaign.prospects")}</span>
        <textarea className="h-36 w-full rounded-xl border-2 border-line bg-surface px-3 py-2 font-mono text-sm" value={text} placeholder={t("guest.campaign.prospectsHint")} onChange={(e) => setText(e.target.value)} />
      </label>
      <label className="inline-flex cursor-pointer items-center gap-2 text-sm font-semibold text-accent">
        <Upload className="h-4 w-4" /> {t("guest.campaign.uploadCsv")}
        <input type="file" accept=".csv,text/csv,text/plain" className="sr-only" onChange={(e) => void onFile(e)} />
      </label>
      <p className="text-sm text-muted">{t("guest.campaign.previewCount", { count: preview.rows.length, bad: preview.bad })}</p>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      <Button loading={busy} onClick={submit}>{t("guest.campaign.generate")}</Button>
      <p className="text-xs text-muted">{t("guest.campaign.aiNote")}</p>
    </Card>
  );
}

function ProspectCard({ p, onChange }: { p: Prospect; onChange: () => void }) {
  const { t } = useTranslation();
  const [subject, setSubject] = useState(p.subject);
  const [body, setBody] = useState(p.body);
  const [busy, setBusy] = useState<"" | "save" | "send" | "regen">("");
  const [msg, setMsg] = useState("");
  const [qr, setQr] = useState(false);
  const dirty = subject !== p.subject || body !== p.body;
  const ready = p.status === "ready";

  async function run(kind: "save" | "send" | "regen", fn: () => Promise<unknown>) {
    setBusy(kind);
    setMsg("");
    try {
      await fn();
      onChange();
    } catch (e) {
      setMsg(errorText(t, e));
    } finally {
      setBusy("");
    }
  }

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-semibold">{p.company}</p>
          <p className="truncate text-sm text-muted">{p.email}{p.industry ? ` · ${p.industry}` : ""}</p>
        </div>
        <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", p.status === "sent" ? "bg-emerald-100 text-emerald-800" : p.status === "failed" ? "bg-red-100 text-red-800" : "bg-surface-2")}>
          {t(`guest.campaign.status.${p.status}`)}
        </span>
      </div>
      {p.status === "generating" && <p className="text-sm text-muted">{t("guest.campaign.generating")}</p>}
      {p.status === "failed" && <p className="text-sm text-bad">{t("guest.campaign.failed")}</p>}
      {p.link && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <a href={p.link.url} target="_blank" rel="noreferrer" className="max-w-full truncate font-semibold text-accent underline">{t("guest.campaign.previewDemo")}</a>
          <Button variant="ghost" className="px-2 py-1 text-sm" onClick={() => copyText(p.link!.url)}><Copy className="h-4 w-4" /> {t("guest.copy")}</Button>
          <Button variant="ghost" className="px-2 py-1 text-sm" onClick={() => setQr(true)}><QrCode className="h-4 w-4" /> {t("guest.qr")}</Button>
          <span className="text-muted">{t("guest.campaign.linkStats", { n: p.link.uses, s: p.link.signups })}</span>
        </div>
      )}
      {(ready || p.status === "sent") && (
        <>
          <Field label={t("guest.campaign.subjectDraft")} value={subject} maxLength={160} disabled={p.status === "sent"} onChange={(e) => setSubject(e.target.value)} />
          <label className="block space-y-1"><span className="text-sm font-medium">{t("guest.campaign.body")}</span>
            <textarea className="h-40 w-full rounded-xl border-2 border-line bg-surface px-3 py-2 text-sm" value={body} maxLength={4000} disabled={p.status === "sent"} onChange={(e) => setBody(e.target.value)} />
          </label>
          <p className="text-xs text-muted">{t("guest.campaign.subjectNote", { subject: p.send_subject ?? "" })}</p>
          <div className="flex flex-wrap gap-2">
            {ready && dirty && <Button variant="outline" className="py-1.5 text-sm" loading={busy === "save"} onClick={() => run("save", () => guests.editProspect(p.id, { subject, body }))}>{t("guest.save")}</Button>}
            <Button variant="ghost" className="py-1.5 text-sm" onClick={() => copyText(`${subject}\n\n${p.send_body ?? body}`)}><Mail className="h-4 w-4" /> {t("guest.campaign.copyEmail")}</Button>
            {ready && (
              <Button className="py-1.5 text-sm" loading={busy === "send"} disabled={dirty} onClick={async () => {
                if (await confirmDialog(t("guest.campaign.confirmSend", { email: p.email }))) void run("send", () => guests.send(p.id));
              }}><Send className="h-4 w-4" /> {t("guest.campaign.send")}</Button>
            )}
          </div>
        </>
      )}
      <div className="flex flex-wrap gap-2">
        {(ready || p.status === "failed") && <Button variant="ghost" className="py-1.5 text-sm" loading={busy === "regen"} onClick={() => run("regen", () => guests.regenerate(p.id))}><RefreshCw className="h-4 w-4" /> {t("guest.campaign.regenerate")}</Button>}
        {p.status !== "sent" && <Button variant="ghost" className="py-1.5 text-sm text-bad" onClick={async () => (await confirmDialog(t("guest.campaign.confirmRemove"), { danger: true })) && void run("save", () => guests.removeProspect(p.id))}><Trash2 className="h-4 w-4" /> {t("guest.delete")}</Button>}
      </div>
      {msg && <p role="alert" className="text-sm text-bad">{msg}</p>}
      {qr && p.link && <Modal title={t("guest.qrTitle", { label: p.company })} onClose={() => setQr(false)}><QrPreview linkId={p.link.id} slug={p.link.slug} /></Modal>}
    </Card>
  );
}

function CampaignDetail({ id, onBack }: { id: number; onBack: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: c, refetch } = useQuery({
    queryKey: ["guest-campaign", id], queryFn: () => guests.campaign(id),
    refetchInterval: (q) => (q.state.data?.prospects?.some((p) => p.status === "generating") ? 4000 : false),
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  if (!c) return <p className="text-muted">{t("common.loading")}</p>;
  const readyN = c.prospects?.filter((p) => p.status === "ready").length ?? 0;

  async function sendAll() {
    if (!(await confirmDialog(t("guest.campaign.confirmSendAll", { count: readyN })))) return;
    setBusy(true);
    setMsg("");
    try {
      const r = await guests.sendAll(id);
      const sentAll = t("guest.campaign.sentAll", { n: r.sent.length, skipped: Object.keys(r.skipped).length });
      setMsg(Object.values(r.skipped).includes("email_not_configured") ? `${sentAll} ${t("mailSetup.notReady")}` : sentAll);
      await refetch();
    } catch (e) {
      setMsg(errorText(t, e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <Button variant="ghost" onClick={onBack}><ArrowLeft className="h-4 w-4" /> {t("guest.campaign.back")}</Button>
      <Card className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-bold">{c.name}</h2>
          <p className="text-sm text-muted">{c.topic} · {t("guest.campaign.sendsToday", { n: c.sends_today ?? 0, max: c.sends_per_day ?? 0 })}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button loading={busy} disabled={!readyN} onClick={sendAll}><Send className="h-4 w-4" /> {t("guest.campaign.sendAll", { n: readyN })}</Button>
          <Button variant="ghost" className="text-bad" onClick={async () => {
            if (!(await confirmDialog(t("guest.campaign.confirmDelete"), { danger: true }))) return;
            await guests.removeCampaign(id);
            void qc.invalidateQueries({ queryKey: ["guest-campaigns"] });
            onBack();
          }}><Trash2 className="h-4 w-4" /> {t("guest.delete")}</Button>
        </div>
      </Card>
      {msg && <p role="status" className="text-sm">{msg}</p>}
      <p className="text-xs text-muted">{t("guest.campaign.unsubNote")}</p>
      {c.prospects?.map((p) => <ProspectCard key={`${p.id}-${p.status}-${p.course_id}`} p={p} onChange={() => void refetch()} />)}
    </div>
  );
}

export function CampaignsTab({ org }: { org: string }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data, error } = useQuery({ queryKey: ["guest-campaigns", org], queryFn: () => guests.campaigns(org) });
  const [open, setOpen] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  if (open) return <CampaignDetail id={open} onBack={() => setOpen(null)} />;
  if (error) return <Card className="text-muted">{t("guest.noAccess")}</Card>;
  return (
    <div className="space-y-3">
      <div className="flex justify-end"><Button onClick={() => setCreating((v) => !v)}><Plus className="h-4 w-4" /> {t("guest.campaign.new")}</Button></div>
      {creating && <NewCampaign org={org} onDone={(c) => { setCreating(false); void qc.invalidateQueries({ queryKey: ["guest-campaigns", org] }); setOpen(c.id); }} />}
      {data && !data.length && !creating && <Card className="text-center text-muted">{t("guest.campaign.empty")}</Card>}
      {data?.map((c) => (
        <Card key={c.id} className="flex cursor-pointer flex-wrap items-center justify-between gap-2 p-4 hover:border-accent" onClick={() => setOpen(c.id)}>
          <div>
            <p className="font-semibold">{c.name}</p>
            <p className="text-sm text-muted">{c.topic} · {new Date(c.created_at).toLocaleDateString(localeOf(i18n.language))}</p>
          </div>
          <p className="text-sm text-muted">{t("guest.campaign.sentOf", { n: c.sent, total: c.prospects_count })}</p>
        </Card>
      ))}
    </div>
  );
}
