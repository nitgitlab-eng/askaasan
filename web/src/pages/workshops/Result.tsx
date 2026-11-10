import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Award, BadgeCheck, Bot, CheckCircle2, CircleX, Download, RotateCcw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useParams } from "react-router-dom";

import { Md } from "@/components/Md";
import { PageError } from "@/components/PageState";
import { Button, Card } from "@/components/ui";
import { credentials } from "@/lib/credentials";
import { downloadFile } from "@/lib/download";
import { asPercent, workshops, type AgentTestSummary, type Certificate, type FinalResult } from "@/lib/workshops";
import { Kili } from "@/mascot/Kili";

/** The certificate PDF through the existing credentials endpoint (looked up by code), like the Certificates page. */
function CertificateCard({ cert }: { cert: Certificate }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function download() {
    setBusy(true);
    setErr("");
    try {
      let id = cert.id;
      if (id === undefined && !cert.pdf_url) id = (await credentials.mine()).find((c) => c.code === cert.code)?.id;
      const url = cert.pdf_url?.startsWith("/api/") ? cert.pdf_url : id !== undefined ? credentials.pdfUrl(id) : null;
      if (!url) throw new Error("not_found");
      await downloadFile(url, "certificate.pdf");
    } catch {
      setErr(t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card className="space-y-3">
      <div className="flex items-center gap-3">
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-accent/10 text-accent"><Award className="h-6 w-6" /></span>
        <div>
          <h2 className="font-display text-xl font-bold">{t("workshop.result.cert")}</h2>
          <p className="text-sm text-muted">{t("workshop.result.certNote")}</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button loading={busy} onClick={() => void download()}><Download className="h-4 w-4" /> {t("workshop.result.download")}</Button>
        <Link to={`/verify/${encodeURIComponent(cert.code)}`} target="_blank" rel="noopener" className="inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 font-semibold text-accent hover:bg-surface-2">
          <BadgeCheck className="h-4 w-4" /> {t("workshop.result.verify")}
        </Link>
      </div>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </Card>
  );
}

/** How the learner's saved agent did on the hidden questions: a score per test and the tools it used, never the answer key. */
function AgentTestsCard({ score, tests }: { score: number | null | undefined; tests: AgentTestSummary[] }) {
  const { t } = useTranslation();
  return (
    <Card className="space-y-3" data-testid="agent-tests">
      <div className="flex items-center gap-3">
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-accent/10 text-accent"><Bot className="h-6 w-6" aria-hidden /></span>
        <div>
          <h2 className="font-display text-xl font-bold">{t("workshop.agent.result.title")}</h2>
          {score != null && <p className="text-sm text-muted">{t("workshop.agent.result.score", { n: asPercent(score) })}</p>}
        </div>
      </div>
      <ul className="space-y-2">
        {tests.map((x, i) => (
          <li key={i} className="space-y-1 rounded-xl border-2 border-line px-3 py-2.5">
            <p className="flex flex-wrap items-center gap-2 font-semibold">
              {x.passed ? <CheckCircle2 className="h-5 w-5 shrink-0 text-good" aria-hidden /> : <CircleX className="h-5 w-5 shrink-0 text-bad" aria-hidden />}
              <span className="min-w-0 flex-1 break-words">{x.label || t("workshop.agent.result.test", { n: (x.index ?? i) + 1 })}</span>
              <span className={x.passed ? "text-good" : "text-bad"}>{x.passed ? t("workshop.agent.result.passed") : t("workshop.agent.result.missed")} · {asPercent(x.score)}%</span>
            </p>
            <p className="text-sm text-muted">{x.tools_used?.length ? t("workshop.agent.result.tools", { list: x.tools_used.join(", ") }) : t("workshop.agent.result.noTools")}</p>
            {x.feedback && <p className="whitespace-pre-wrap break-words text-sm">{x.feedback}</p>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** The API scores and pass marks as fractions (0.6 = 60%); show whole percentages. */

export default function WorkshopResultPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const sid = Number(id);
  const fresh = (useLocation().state as { result?: FinalResult } | null)?.result;
  const { data: session, error, refetch } = useQuery({ queryKey: ["workshop-session", sid], queryFn: () => workshops.session(sid), enabled: sid > 0 });
  if (!(sid > 0)) return <PageError notFound />;
  if (error && !fresh) return <PageError error={error} onRetry={() => void refetch()} />;
  if (!session && !fresh) return <div className="p-8 text-muted">…</div>;

  const score = fresh?.score ?? session?.final_score ?? null;
  const passed = fresh?.passed ?? session?.passed ?? null;
  const cert = fresh?.certificate ?? session?.certificate ?? null;
  const passMark = session?.workshop.pass_mark;
  const agentScore = fresh?.agent_score ?? session?.agent_score ?? null;
  const agentTests = fresh?.agent_tests ?? session?.agent_tests ?? [];

  return (
    <div className="mx-auto max-w-3xl space-y-5 px-4 py-8">
      {session && <p className="break-words text-sm font-semibold uppercase tracking-wide text-accent">{session.workshop.title}</p>}
      {score === null ? (
        <Card className="space-y-3 text-center">
          <Kili mood="idle" size={96} />
          <h1 className="text-lg">{t("workshop.result.none")}</h1>
          <Link to={`/workshops/session/${sid}`} className="font-semibold text-accent">{t("workshop.result.toSession")}</Link>
        </Card>
      ) : (
        <>
          <header className="flex items-center gap-4">
            <Kili mood={passed ? "celebrate" : "hmm"} size={104} />
            <div>
              <h1 className="font-display text-3xl font-extrabold">{passed ? t("workshop.result.passed") : t("workshop.result.failed")}</h1>
              <p className="text-lg text-muted">
                {t("workshop.result.score", { n: asPercent(score) })}
                {passMark != null && ` · ${t("workshop.result.passMark", { n: asPercent(passMark) })}`}
              </p>
            </div>
          </header>
          {fresh?.feedback && (
            <Card className="prose-chat space-y-2">
              <h2 className="font-display text-lg font-bold">{t("workshop.result.feedback")}</h2>
              <Md ai>{fresh.feedback}</Md>
            </Card>
          )}
          {(agentTests.length > 0 || agentScore != null) && <AgentTestsCard score={agentScore} tests={agentTests} />}
          {cert && <CertificateCard cert={cert} />}
          {!passed && (
            <Link to={`/workshops/session/${sid}`} className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 font-semibold text-accent-ink">
              <RotateCcw className="h-4 w-4" /> {t("workshop.result.retry")}
            </Link>
          )}
        </>
      )}
      <Link to="/workshops" className="flex items-center gap-1.5 font-semibold text-muted hover:text-ink"><ArrowLeft className="h-4 w-4" /> {t("workshop.result.back")}</Link>
    </div>
  );
}
