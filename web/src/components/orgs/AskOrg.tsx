import { MessageCircleQuestion, Send } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { AskAnswer } from "@/components/study/AskAnswer";
import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { orgs, type OrgAskResult } from "@/lib/orgs";

/** Cockpit Overview: ask about your organisation in plain language; the answer is a chart (and a first-name table). */
export function AskOrg({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const [ans, setAns] = useState<OrgAskResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function go(e: FormEvent) {
    e.preventDefault();
    if (q.trim().length < 3) return;
    setBusy(true);
    setErr("");
    try {
      setAns(await orgs.ask(slug, q.trim()));
    } catch (x) {
      const code = x instanceof ApiError ? String(x.data?.code ?? "") : "";
      setErr(code === "ai_budget_exceeded" ? t("paths.budget") : code === "bad_scope" ? t("org.ask.badScope") : x instanceof ApiError && x.status === 429 ? t("org.ask.tooMany") : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card className="space-y-3">
      <h2 className="flex items-center gap-2 font-display text-lg font-bold"><MessageCircleQuestion className="h-5 w-5 text-accent" /> {t("org.ask.title")}</h2>
      <form onSubmit={(e) => void go(e)} className="flex gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={300} placeholder={t("org.ask.placeholder")} aria-label={t("org.ask.title")}
          className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent" />
        <Button type="submit" loading={busy} disabled={q.trim().length < 3} aria-label={t("mentor.send")}><Send className="h-4 w-4" /></Button>
      </form>
      <div className="flex flex-wrap gap-2">
        {(t("org.ask.examples", { returnObjects: true }) as string[]).map((ex) => (
          <button key={ex} type="button" onClick={() => setQ(ex)} className="rounded-full border border-line px-3 py-1 text-xs hover:border-accent">{ex}</button>
        ))}
      </div>
      {ans && <AskAnswer ans={ans} unsupported={t("org.ask.unsupported")} empty={t("org.ask.noData")} columnLabel={(c) => t(`org.ask.col.${c}`, { defaultValue: c })} />}
      {ans?.supported && <p className="text-xs text-muted">{ans.class ? t("org.ask.howClass", { name: ans.class }) : t("org.ask.how")}</p>}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </Card>
  );
}
