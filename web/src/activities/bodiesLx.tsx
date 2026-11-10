import { CheckCircle2, Globe, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import { artifactItemLabel, isHttpsUrl, type ArtifactItem } from "./lxArtifact";
import type { BodyProps } from "./types";

/** 🌐 Publish something (Google Site, GitHub Pages, Canva …) and paste its https:// link; the server checks the live page. */
export function ArtifactCheckBody({ payload, answer, setAnswer, result, locked }: BodyProps<{ url?: string }>) {
  const { t } = useTranslation();
  const steps = (payload.steps ?? []) as string[];
  const checklist = (payload.checklist ?? []) as ArtifactItem[];
  const url = answer.url ?? "";
  const reveal = result?.reveal ?? {};
  const missing = (reveal.missing ?? []) as ArtifactItem[];
  return (
    <div className="space-y-3">
      {steps.length > 0 && (
        <div>
          <p className="text-sm font-semibold">{t("lx.artifact.steps")}</p>
          <ol className="list-decimal space-y-1 pl-5">{steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
        </div>
      )}
      {checklist.length > 0 ? (
        <div className="rounded-xl bg-surface-2 p-3 text-sm">
          <p className="font-semibold">{t("lx.artifact.checklist")}</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">{checklist.map((c, i) => <li key={i}>{artifactItemLabel(t, c)}</li>)}</ul>
        </div>
      ) : payload.n_checks ? <p className="text-sm text-muted">{t("lx.artifact.hidden", { count: payload.n_checks })}</p> : null}
      <label className="block space-y-1 text-sm font-medium">
        <span className="flex items-center gap-1.5"><Globe className="h-4 w-4 text-accent" /> {t("lx.artifact.urlLabel")}</span>
        <input type="url" inputMode="url" autoComplete="off" spellCheck={false} value={url} disabled={locked} placeholder="https://"
          onChange={(e) => setAnswer({ url: e.target.value })}
          className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent" />
        {url.trim() && !isHttpsUrl(url) && <span className="text-xs text-bad">{t("lx.artifact.mustHttps")}</span>}
      </label>
      <p className="text-xs text-muted">{t("lx.artifact.privacy")}</p>
      {result && reveal.status === "live" && <p className="flex items-center gap-1.5 font-semibold text-good"><CheckCircle2 className="h-4 w-4" /> {t("lx.artifact.live")}</p>}
      {result && reveal.status === "missing" && (
        <div className="text-sm">
          <p className="font-semibold">{t("lx.artifact.missing")}</p>
          <ul className="mt-1 space-y-0.5">{missing.map((c, i) => <li key={i} className="flex items-center gap-1.5 text-bad"><XCircle className="h-4 w-4 shrink-0" /> {artifactItemLabel(t, c)}</li>)}</ul>
        </div>
      )}
      {result && reveal.status === "unreachable" && <p className="text-sm text-bad">{t("lx.artifact.unreachable")}</p>}
      {result && reveal.status === "refused" && <p className="text-sm text-bad">{t("lx.artifact.refused")}</p>}
    </div>
  );
}
