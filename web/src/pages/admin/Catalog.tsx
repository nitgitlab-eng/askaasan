import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { promptDialog } from "@/lib/dialog";
import { Button, Card } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

interface Pending {
  id: number;
  title: string;
  description: string;
  cover_emoji: string;
  owner_email: string;
  lessons: number;
  share_token: string;
}

export default function AdminCatalog() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["moderation"], queryFn: () => api<Pending[]>("/api/admin/catalog/") });
  const decide = useMutation({
    mutationFn: ({ id, decision, note }: { id: number; decision: "approve" | "reject"; note?: string }) =>
      api(`/api/admin/catalog/${id}/`, { method: "POST", json: { decision, note } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["moderation"] }),
  });
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState("");
  async function grant(e: FormEvent, on: boolean) {
    e.preventDefault();
    try {
      const r = await api<{ email: string; is_creator: boolean }>("/api/admin/creators/", { method: "POST", json: { email, is_creator: on } });
      setMsg(`${r.email}: ${r.is_creator ? t("admin.granted") : t("admin.revoked")}`);
    } catch (err) {
      setMsg(err instanceof ApiError && err.status === 404 ? t("admin.noUser") : t("mentor.errors.generic"));
    }
  }
  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("admin.catalogTitle")}</h1>
        <p className="text-muted">{t("admin.catalogSub")}</p>
      </header>
      <Card className="space-y-2">
        <h2 className="font-display text-xl font-bold">{t("admin.creators")}</h2>
        <form className="flex flex-wrap gap-2" onSubmit={(e) => grant(e, true)}>
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="teacher@school.in" className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2" aria-label={t("auth.email")} />
          <Button type="submit">{t("admin.grant")}</Button>
          <Button type="button" variant="outline" onClick={(e) => grant(e as unknown as FormEvent, false)}>{t("admin.revoke")}</Button>
        </form>
        {msg && <p role="status" className="text-sm text-muted">{msg}</p>}
      </Card>
      <h2 className="font-display text-xl font-bold">{t("admin.pending")} ({data?.length ?? 0})</h2>
      {data?.map((c) => (
        <Card key={c.id} className="space-y-2">
          <div className="flex items-start gap-3">
            <span className="text-3xl">{c.cover_emoji}</span>
            <div className="flex-1">
              <p className="font-display text-lg font-bold">{c.title}</p>
              <p className="text-sm text-muted">{c.description}</p>
              <p className="text-xs text-muted">{c.owner_email} · {t("catalog.lessons", { count: c.lessons })} · <a className="text-accent" href={`/s/${c.share_token}`} target="_blank" rel="noreferrer">{t("admin.review")}</a></p>
            </div>
          </div>
          <div className="flex gap-2">
            <Button onClick={() => decide.mutate({ id: c.id, decision: "approve" })}><Check className="h-4 w-4" /> {t("admin.approve")}</Button>
            <Button variant="outline" onClick={async () => { const note = await promptDialog(t("admin.reason"), { allowEmpty: true, ok: t("admin.reject") }); if (note !== null) decide.mutate({ id: c.id, decision: "reject", note }); }}><X className="h-4 w-4" /> {t("admin.reject")}</Button>
          </div>
        </Card>
      ))}
    </div>
  );
}
