import { ShieldCheck } from "lucide-react";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { Proctoring } from "@/lib/workshops";

/**
 * "What we track", worded the same everywhere a learner meets it (run details, the lobby and the prerequisites screen):
 * the proctoring mode in plain words, what is recorded (when known), the institution line for org runs, and no camera.
 * `attention` says whether an institution also sees attention activity; it defaults to "proctoring is on".
 */
export function ProctorNotice({ mode, org = false, attention, tracked, as: Heading = "p" }: {
  mode: Proctoring; org?: boolean; attention?: boolean; tracked?: string[]; as?: "p" | "h2";
}) {
  const { t } = useTranslation();
  const titleId = useId();
  const seesAttention = attention ?? mode !== "off";
  return (
    <section aria-labelledby={titleId} data-testid="proctor-box" className="flex gap-3 rounded-2xl bg-surface-2 p-4">
      <ShieldCheck className="h-6 w-6 shrink-0 text-good" aria-hidden />
      <div className="min-w-0 space-y-1">
        <Heading id={titleId} className="font-display text-lg font-bold">{t("workshop.proctor.title")}</Heading>
        <p data-testid="proctor-notice">{t(`workshop.proctor.${mode}`)}</p>
        {!!tracked?.length && (
          <ul aria-label={t("workshop.proctor.title")} className="flex flex-wrap gap-1.5 pt-1">
            {tracked.map((k) => <li key={k} className="rounded-full bg-surface px-2.5 py-0.5 text-sm">{t(`workshop.pub.tracked.${k}`, { defaultValue: k })}</li>)}
          </ul>
        )}
        {/* Institution runs: their staff see a live dashboard of this session. */}
        {org && <p data-testid="org-notice" className="font-medium">{t(seesAttention ? "workshop.proctor.orgAttention" : "workshop.proctor.org")}</p>}
        <p className="text-sm text-muted">{t("workshop.pub.noCamera")}</p>
      </div>
    </section>
  );
}
