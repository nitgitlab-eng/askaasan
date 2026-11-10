import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";

interface Row { id: number; category: string; text: string; page: string; status: string; reply: string; replied_at: string | null; created_at: string; screenshot: string; ref: string; browser: string; email: string; user: string | null }
interface Art { id: number; slug: string; category: string; title: string; title_ta: string; body_md: string; body_ta_md: string; order: number; published: boolean }
const STATUSES = ["new", "triaging", "fixed", "closed"] as const;
const CATEGORIES = ["start", "learn", "teach", "account", "faq"] as const;
const input = "w-full rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm";

function Inbox() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [st, setSt] = useState("new");
  const { data } = useQuery({ queryKey: ["admin-reports", st], queryFn: () => api<{ counts: Record<string, number>; rows: Row[] }>(`/api/admin/reports/?status=${st}`) });
  const [reply, setReply] = useState<Record<number, string>>({});
  const [notice, setNotice] = useState("");
  const save = async (id: number, body: object) => {
    const r = await api<{ emailed?: boolean; code?: string }>(`/api/admin/reports/${id}/`, { method: "PATCH", json: body });
    // the reply is saved (and shown to a signed-in reporter in their notifications) even when no email went out
    if (r.emailed === false) setNotice(t(r.code === "email_not_configured" ? "admin.support.replyNotConfigured" : "admin.support.replyFailed", { id }));
    else if (r.emailed) setNotice("");
    void qc.invalidateQueries({ queryKey: ["admin-reports"] });
  };
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-display text-xl font-bold">{t("admin.support.reports")}</h2>
        <div className="ml-auto flex gap-1 rounded-xl bg-surface-2 p-1 text-sm">
          {STATUSES.map((s) => <button key={s} onClick={() => setSt(s)} className={cn("rounded-lg px-3 py-1 font-semibold capitalize", st === s ? "bg-surface shadow" : "text-muted")}>{t(`admin.support.statuses.${s}`)} ({data?.counts[s] ?? 0})</button>)}
        </div>
      </div>
      {notice && <p role="status" className="rounded-lg bg-bad/10 px-3 py-2 text-sm">{notice}</p>}
      {!data?.rows.length && <p className="text-sm text-muted">{t("admin.support.empty")}</p>}
      {data?.rows.map((r) => (
        <div key={r.id} className="space-y-2 rounded-xl border border-line p-3 text-sm">
          <p className="flex flex-wrap items-center gap-2"><b>#{r.id}</b><span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs">{r.category}</span>
            <span className="text-muted">{r.email} · {new Date(r.created_at).toLocaleString("en-IN")}</span>
            <select value={r.status} onChange={(e) => void save(r.id, { status: e.target.value })} className="ml-auto rounded-lg border border-line bg-surface px-2 py-1 text-xs" aria-label={t("admin.common.status")}>
              {STATUSES.map((s) => <option key={s} value={s}>{t(`admin.support.statuses.${s}`)}</option>)}
            </select></p>
          <p className="whitespace-pre-line">{r.text}</p>
          <p className="text-xs text-muted">{r.page && <>{t("admin.support.page", { page: r.page })} · </>}{r.ref && <>{t("admin.support.about", { ref: r.ref })} · </>}{r.browser.slice(0, 80)}</p>
          {r.screenshot && <a href={r.screenshot} target="_blank" rel="noreferrer"><img src={r.screenshot} alt={t("admin.support.screenshot")} className="max-h-40 rounded-lg border border-line" /></a>}
          {r.reply ? <p className="rounded-lg bg-accent/10 px-3 py-2"><b>{t("admin.support.replied")}</b> {r.reply}</p> : (
            <div className="flex gap-2">
              <textarea value={reply[r.id] ?? ""} onChange={(e) => setReply({ ...reply, [r.id]: e.target.value })} rows={2} placeholder={t("admin.support.replyPh")} className={input} />
              <Button className="self-end py-1.5 text-sm" disabled={!reply[r.id]?.trim()} onClick={() => void save(r.id, { reply: reply[r.id], status: r.status === "new" ? "triaging" : r.status })}>{t("admin.support.send")}</Button>
            </div>
          )}
        </div>
      ))}
    </Card>
  );
}

function Articles() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["admin-help"], queryFn: () => api<Art[]>("/api/admin/help/") });
  const [edit, setEdit] = useState<Partial<Art> | null>(null);
  const [err, setErr] = useState("");
  async function save() {
    if (!edit) return;
    setErr("");
    try {
      if (edit.id) await api(`/api/admin/help/${edit.id}/`, { method: "PATCH", json: edit });
      else await api("/api/admin/help/", { method: "POST", json: edit });
      setEdit(null);
      void qc.invalidateQueries({ queryKey: ["admin-help"] });
    } catch (e) {
      setErr(e instanceof ApiError ? JSON.stringify(e.data) : t("admin.support.failed"));
    }
  }
  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-xl font-bold">{t("admin.support.articles")}</h2>
        {!edit && <Button variant="outline" onClick={() => setEdit({ slug: "", category: "faq", title: "", body_md: "", title_ta: "", body_ta_md: "", published: true, order: 50 })}><Plus className="h-4 w-4" /> {t("admin.support.newArticle")}</Button>}
      </div>
      {edit && (
        <div className="space-y-2 rounded-xl border-2 border-dashed border-accent/40 p-3 text-sm">
          <div className="grid gap-2 sm:grid-cols-3">
            <label>{t("admin.support.slug")}<input value={edit.slug} onChange={(e) => setEdit({ ...edit, slug: e.target.value })} className={input} /></label>
            <label>{t("admin.support.category")}<select value={edit.category} onChange={(e) => setEdit({ ...edit, category: e.target.value })} className={input}>{CATEGORIES.map((c) => <option key={c} value={c}>{t(`admin.support.categories.${c}`)}</option>)}</select></label>
            <label className="flex items-end gap-2"><input type="checkbox" checked={!!edit.published} onChange={(e) => setEdit({ ...edit, published: e.target.checked })} /> {t("admin.support.published")}</label>
          </div>
          <label className="block">{t("admin.support.titleEn")}<input value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} className={input} /></label>
          <label className="block">{t("admin.support.bodyEn")}<textarea rows={6} value={edit.body_md} onChange={(e) => setEdit({ ...edit, body_md: e.target.value })} className={cn(input, "font-mono")} /></label>
          <label className="block">{t("admin.support.titleTa")}<input value={edit.title_ta} onChange={(e) => setEdit({ ...edit, title_ta: e.target.value })} className={input} /></label>
          <label className="block">{t("admin.support.bodyTa")}<textarea rows={6} value={edit.body_ta_md} onChange={(e) => setEdit({ ...edit, body_ta_md: e.target.value })} className={cn(input, "font-mono")} /></label>
          {err && <p className="text-bad">{err}</p>}
          <div className="flex gap-2"><Button onClick={() => void save()}>{t("admin.common.save")}</Button><Button variant="ghost" onClick={() => setEdit(null)}>{t("admin.common.cancel")}</Button></div>
        </div>
      )}
      <ul className="divide-y divide-line text-sm">
        {data?.map((a) => (
          <li key={a.id} className="flex items-center gap-2 py-1.5">
            <span className="w-16 text-xs text-muted">{(CATEGORIES as readonly string[]).includes(a.category) ? t(`admin.support.categories.${a.category}`) : a.category}</span>
            <span className={cn("flex-1", !a.published && "text-muted line-through")}>{a.title} {!a.body_ta_md && <span className="text-xs text-bad">{t("admin.support.noTamil")}</span>}</span>
            <button className="text-accent" onClick={() => setEdit(a)}>{t("admin.support.edit")}</button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** Super admin: problem reports inbox (status + email reply) and help-centre articles. */
export default function AdminSupport() {
  const { t } = useTranslation();
  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <h1 className="font-display text-3xl font-extrabold">{t("admin.support.title")}</h1>
      <Inbox />
      <Articles />
    </div>
  );
}
