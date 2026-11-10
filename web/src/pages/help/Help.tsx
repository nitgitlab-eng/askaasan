import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ImagePlus, LifeBuoy, PlayCircle, Search, Send, Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import Markdown from "react-markdown";
import { Link, useParams, useSearchParams } from "react-router-dom";
import remarkGfm from "remark-gfm";

import { Md } from "@/components/Md";
import { localeOf } from "@/i18n/languages";
import { startTour } from "@/components/tour/tourStore";
import { Button, Card, Segmented } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { media } from "@/lib/media";
import { support, type ArticleRow } from "@/lib/support";
import { useMe } from "@/lib/useMe";

const CATS = ["start", "learn", "teach", "account", "faq"];
const REPORT_CATS = ["bug", "answer", "content", "billing", "account", "idea", "other"];

function useTitle() {
  const { i18n } = useTranslation();
  return (a: ArticleRow) => (i18n.language === "ta" && a.title_ta ? a.title_ta : a.title);
}

function ArticleView({ slug }: { slug: string }) {
  const { t, i18n } = useTranslation();
  const title = useTitle();
  const { data, error } = useQuery({ queryKey: ["help-article", slug], queryFn: () => support.article(slug), retry: false });
  if (error) return <p className="text-muted">{t("help.notFound")}</p>;
  if (!data) return <p className="text-muted">{t("common.loading")}</p>;
  const body = i18n.language === "ta" && data.body_ta_md ? data.body_ta_md : data.body_md;
  return (
    <Card className="space-y-3">
      <Link to="/help" className="inline-flex items-center gap-1 text-sm text-muted hover:text-accent"><ArrowLeft className="h-4 w-4" /> {t("help.title")}</Link>
      <h1 className="font-display text-2xl font-extrabold">{title(data)}</h1>
      <div className="prose-chat"><Markdown remarkPlugins={[remarkGfm]}>{body}</Markdown></div>
      <p className="text-sm text-muted">{t("help.stillStuck")} <Link to="/help?tab=report" className="font-semibold text-accent">{t("help.report")}</Link></p>
    </Card>
  );
}

function AskHelp() {
  const { t } = useTranslation();
  const title = useTitle();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [ans, setAns] = useState<{ answer: string; sources: ArticleRow[]; found: boolean } | null>(null);
  const [err, setErr] = useState("");
  async function ask(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      setAns(await support.ask(q.trim()));
    } catch (x) {
      setErr(x instanceof ApiError && x.status === 429 ? t("help.tooMany") : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card className="space-y-3">
      <h2 className="flex items-center gap-2 font-display text-lg font-bold"><Sparkles className="h-5 w-5 text-accent" /> {t("help.ask")}</h2>
      <form onSubmit={(e) => void ask(e)} className="flex gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={500} placeholder={t("help.askPh")} aria-label={t("help.ask")}
          className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent" />
        <Button type="submit" loading={busy} disabled={q.trim().length < 3} aria-label={t("mentor.send")}><Send className="h-4 w-4" /></Button>
      </form>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      {ans && (
        <div className="space-y-2 rounded-xl bg-surface-2 p-3 text-sm">
          {ans.answer ? <div className="prose-chat"><Md ai>{ans.answer}</Md></div> : <p>{t("help.noAnswer")}</p>}
          {!!ans.sources.length && <p className="text-xs">{t("help.from")} {ans.sources.map((s, i) => <span key={s.slug}>{i > 0 && " · "}<Link to={`/help/${s.slug}`} className="font-semibold text-accent">{title(s)}</Link></span>)}</p>}
          {!ans.found && <Link to="/help?tab=report" className="text-xs font-semibold text-accent">{t("help.report")} →</Link>}
          <p className="text-[11px] text-muted">{t("help.aiNote")}</p>
        </div>
      )}
    </Card>
  );
}

function ReportForm() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const fromAnswer = params.get("report") === "answer";
  const [cat, setCat] = useState(fromAnswer ? "answer" : "bug");
  const [text, setText] = useState("");
  const [shot, setShot] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState("");
  const ref = fromAnswer && params.get("kind") && params.get("id") ? `answer:${params.get("kind")}:${params.get("id")}` : "";
  async function send(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await support.report({ category: cat, text: text.trim(), page: params.get("from") ?? document.referrer.replace(location.origin, "").slice(0, 300), ref,
        screenshot: shot || undefined, browser: navigator.userAgent.slice(0, 300) });
      setDone(true);
      void qc.invalidateQueries({ queryKey: ["my-reports"] });
    } catch (x) {
      setErr(x instanceof ApiError && x.status === 429 ? t("help.tooMany") : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }
  if (done) return <Card><p role="status" className="py-4 text-center">{t("help.thanks")}</p></Card>;
  return (
    <Card>
      <form onSubmit={(e) => void send(e)} className="space-y-3">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold"><LifeBuoy className="h-5 w-5 text-accent" /> {t("help.report")}</h2>
        {ref && <p className="rounded-lg bg-surface-2 px-3 py-1.5 text-xs">{t("help.aboutAnswer")}</p>}
        <label className="block text-sm font-medium">{t("help.what")}
          <select value={cat} onChange={(e) => setCat(e.target.value)} className="mt-1 block rounded-xl border-2 border-line bg-surface px-3 py-2">
            {REPORT_CATS.map((c) => <option key={c} value={c}>{t(`help.cat.${c}`)}</option>)}
          </select>
        </label>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} minLength={5} maxLength={4000} required placeholder={t("help.describe")} aria-label={t("help.describe")}
          className="w-full rounded-xl border-2 border-line bg-surface p-3 outline-none focus:border-accent" />
        <div className="flex flex-wrap items-center gap-3">
          {shot ? <img src={shot} alt="" className="h-16 rounded-lg border border-line" /> : null}
          <label className="flex cursor-pointer items-center gap-1 text-sm font-semibold text-accent">
            <ImagePlus className="h-4 w-4" /> {shot ? t("help.changeShot") : t("help.addShot")}
            <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              try { setShot((await media.upload(f, "problem screenshot")).url); } catch { setErr(t("mentor.errors.generic")); }
            }} />
          </label>
        </div>
        <p className="text-xs text-muted">{t("help.privacy")}</p>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        <Button type="submit" loading={busy} disabled={text.trim().length < 5}>{t("help.send")}</Button>
      </form>
    </Card>
  );
}

function MyReports() {
  const { t, i18n } = useTranslation();
  const { data } = useQuery({ queryKey: ["my-reports"], queryFn: support.reports });
  if (!data?.length) return <Card><p className="text-sm text-muted">{t("help.noReports")}</p></Card>;
  return (
    <div className="space-y-2">
      {data.map((r) => (
        <Card key={r.id} className="space-y-1 text-sm">
          <p className="flex items-center gap-2"><b>#{r.id}</b> <span className="text-muted">{t(`help.cat.${r.category}`)} · {new Date(r.created_at).toLocaleDateString(localeOf(i18n.language))}</span>
            <span className={cn("ml-auto rounded-full px-2 py-0.5 text-xs font-semibold", r.status === "fixed" ? "bg-good/15 text-good" : "bg-surface-2 text-muted")}>{t(`help.status.${r.status}`)}</span></p>
          <p className="whitespace-pre-line">{r.text}</p>
          {r.reply && <p className="rounded-lg bg-accent/10 px-3 py-2"><b>{t("help.reply")}</b> {r.reply}</p>}
        </Card>
      ))}
    </div>
  );
}

/** Help centre: search, browse articles, Ask Help (AI from articles only), report a problem, my reports, replay tours. */
export default function HelpPage() {
  const { t } = useTranslation();
  const { slug } = useParams();
  const [params, setParams] = useSearchParams();
  const title = useTitle();
  const { data: me } = useMe();
  const [q, setQ] = useState("");
  const { data: rows } = useQuery({ queryKey: ["help-articles", q], queryFn: () => support.articles(q.trim()) });
  const tab = params.get("report") ? "report" : (params.get("tab") ?? "browse");
  if (slug) return <div className="mx-auto max-w-3xl space-y-5 px-4 py-8"><ArticleView slug={slug} /></div>;
  return (
    <div className="mx-auto max-w-4xl space-y-5 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("help.title")}</h1>
        <p className="text-muted">{t("help.sub")}</p>
      </header>
      <Segmented label={t("help.title")} value={tab} onChange={(v) => setParams(v === "browse" ? {} : { tab: v })}
        options={[{ value: "browse", label: t("help.tabs.browse") }, { value: "report", label: t("help.tabs.report") }, { value: "reports", label: t("help.tabs.reports") }]} />
      {tab === "browse" && (
        <>
          <AskHelp />
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("help.search")} aria-label={t("help.search")}
              className="w-full rounded-xl border-2 border-line bg-surface py-2 pl-9 pr-3 outline-none focus:border-accent" />
          </div>
          {q.trim() ? (
            <Card><ul className="space-y-1">{rows?.map((a) => <li key={a.slug}><Link to={`/help/${a.slug}`} className="font-medium hover:text-accent">{title(a)}</Link></li>)}
              {rows && !rows.length && <li className="text-sm text-muted">{t("help.nothing")}</li>}</ul></Card>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {CATS.map((c) => {
                const list = rows?.filter((a) => a.category === c) ?? [];
                if (!list.length || (c === "teach" && !me)) return null;
                return (
                  <Card key={c} className="space-y-2">
                    <h2 className="font-display text-lg font-bold">{t(`help.cats.${c}`)}</h2>
                    <ul className="space-y-1 text-sm">{list.map((a) => <li key={a.slug}><Link to={`/help/${a.slug}`} className="hover:text-accent">{title(a)}</Link></li>)}</ul>
                  </Card>
                );
              })}
            </div>
          )}
          <Card className="space-y-2">
            <h2 className="flex items-center gap-2 font-display text-lg font-bold"><PlayCircle className="h-5 w-5 text-accent" /> {t("help.tours")}</h2>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => startTour("app")}>{t("tour.names.app")}</Button>
              {me?.can_author && <Link to="/lab?tour=1" className="rounded-xl border-2 border-line px-4 py-2 font-semibold hover:border-accent">{t("tour.names.lab")}</Link>}
              <Link to="/orgs" className="rounded-xl border-2 border-line px-4 py-2 font-semibold hover:border-accent">{t("tour.names.cockpit")}</Link>
              {me?.is_staff && <Link to="/admin?tour=1" className="rounded-xl border-2 border-line px-4 py-2 font-semibold hover:border-accent">{t("tour.names.admin")}</Link>}
            </div>
          </Card>
        </>
      )}
      {tab === "report" && <ReportForm />}
      {tab === "reports" && <MyReports />}
    </div>
  );
}
