import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Award, Copy, Download, ExternalLink, Eye, EyeOff, Share2, ShieldOff } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { confirmDialog } from "@/lib/dialog";
import { SharePanel } from "@/components/credentials/SharePanel";
import { Button, Card } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { cn } from "@/lib/cn";
import { credentials, type Certificate } from "@/lib/credentials";
import { downloadFile } from "@/lib/download";

function CertCard({ c, onChange }: { c: Certificate; onChange: () => void }) {
  const { t, i18n } = useTranslation();
  const [share, setShare] = useState(false);
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState("");
  const path = new URL(c.verify_url).pathname;
  const act = async (fn: () => Promise<unknown>) => {
    setErr("");
    try {
      await fn();
      onChange();
    } catch {
      setErr(t("mentor.errors.generic"));
    }
  };
  return (
    <Card className={cn("space-y-3", c.revoked && "opacity-70")}>
      <div className="flex flex-wrap items-start gap-3">
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-accent/10 text-accent"><Award className="h-6 w-6" /></span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t(`cred.kind.${c.kind}`)} · {c.issuer}{c.issued_by_type === "organisation" ? ` (${t("credSurvey2.orgOnAasan")})` : ""}</p>
          <h2 className="font-display text-xl font-bold">{c.title}</h2>
          {c.author && <p className="text-xs text-muted">{t("credSurvey2.courseBy", { name: c.author })}</p>}
          <p className="text-sm text-muted">{new Date(c.issued_at).toLocaleDateString(localeOf(i18n.language), { dateStyle: "long" })}
            {c.detail.pct != null && ` · ${t("cred.img.score", { pct: c.detail.pct })}`}</p>
        </div>
        <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-semibold", c.revoked ? "bg-bad/10 text-bad" : c.hidden ? "bg-surface-2 text-muted" : "bg-good/15 text-good")}>
          {c.revoked ? t("cred.status.revoked") : c.hidden ? t("cred.status.hidden") : t("cred.status.public")}
        </span>
      </div>
      {!c.revoked && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Button variant="outline" className="py-1.5 text-sm" onClick={() => void downloadFile(credentials.pdfUrl(c.id), "certificate.pdf").catch(() => setErr(t("mentor.errors.generic")))}>
            <Download className="h-4 w-4" /> PDF
          </Button>
          <Button variant="outline" className="py-1.5 text-sm" onClick={() => setShare(!share)}><Share2 className="h-4 w-4" /> {t("cred.share.button")}</Button>
          {!c.hidden && (
            <>
              <button type="button" className="flex items-center gap-1 font-semibold text-accent" onClick={() => { void navigator.clipboard.writeText(c.verify_url); setCopied(true); }}>
                <Copy className="h-4 w-4" /> {copied ? t("cred.copied") : t("cred.copyLink")}
              </button>
              <Link to={path} target="_blank" rel="noopener" className="flex items-center gap-1 font-semibold text-accent"><ExternalLink className="h-4 w-4" /> {t("cred.open")}</Link>
            </>
          )}
          <button type="button" className="ml-auto flex items-center gap-1 text-muted hover:text-ink" onClick={() => void act(() => credentials.setHidden(c.id, !c.hidden))}>
            {c.hidden ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />} {c.hidden ? t("cred.show") : t("cred.hide")}
          </button>
          <button type="button" className="flex items-center gap-1 text-muted hover:text-bad" onClick={async () => { if (await confirmDialog(t("cred.revokeConfirm"), { danger: true })) void act(() => credentials.revoke(c.id)); }}>
            <ShieldOff className="h-4 w-4" /> {t("cred.revoke")}
          </button>
        </div>
      )}
      {c.hidden && !c.revoked && <p className="text-xs text-muted">{t("cred.hiddenHint")}</p>}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      {share && !c.revoked && <SharePanel src={{ source: "certificate", certificateId: c.id }} />}
    </Card>
  );
}

/** The learner's certificates: download (PDF), share (text + image), verify link, hide or revoke. */
export default function CertificatesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["certificates"], queryFn: credentials.mine });
  return (
    <div className="mx-auto max-w-3xl space-y-5 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("cred.title")}</h1>
        <p className="text-muted">{t("cred.sub")}</p>
      </header>
      {!data ? <p className="text-muted">{t("common.loading")}</p> : !data.length ? <Card className="text-muted">{t("cred.empty")}</Card> : (
        data.map((c) => <CertCard key={c.id} c={c} onChange={() => void qc.invalidateQueries({ queryKey: ["certificates"] })} />)
      )}
    </div>
  );
}
