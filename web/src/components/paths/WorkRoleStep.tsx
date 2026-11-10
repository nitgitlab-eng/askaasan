import { Building2, BriefcaseBusiness } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { learner } from "@/lib/learner";

/** Optional onboarding step: where you work/study (AI summary to confirm) and your role (what it involves + key skills). */
export function WorkRoleStep({ onSkills }: { onSkills: (slugs: string[]) => void }) {
  const { t } = useTranslation();
  const [org, setOrg] = useState("");
  const [role, setRole] = useState("");
  const [orgInfo, setOrgInfo] = useState<{ summary: string; industry: string } | null>(null);
  const [roleInfo, setRoleInfo] = useState<{ summary: string; skills: string[] } | null>(null);
  const [busy, setBusy] = useState<"" | "org" | "role">("");
  const [err, setErr] = useState("");
  const fail = (e: unknown) => setErr(e instanceof ApiError && e.status === 429 ? t("careerPlus.limit") : t("mentor.errors.generic"));
  const field = "min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none focus:border-accent";
  return (
    <div className="space-y-4">
      <h1 className="font-display text-3xl font-extrabold">{t("workRole.title")}</h1>
      <p className="text-sm text-muted">{t("workRole.sub")}</p>
      <form className="flex gap-2" onSubmit={async (e) => {
        e.preventDefault();
        if (org.trim().length < 2) return;
        setErr(""); setBusy("org");
        try { setOrgInfo(await learner.company(org.trim())); } catch (x) { fail(x); } finally { setBusy(""); }
      }}>
        <input value={org} onChange={(e) => setOrg(e.target.value)} maxLength={120} placeholder={t("workRole.orgPh")} aria-label={t("workRole.org")} className={field} />
        <Button type="submit" variant="outline" loading={busy === "org"} disabled={org.trim().length < 2}><Building2 className="h-4 w-4" /> {t("workRole.lookUp")}</Button>
      </form>
      {orgInfo && <p className="rounded-xl bg-surface-2 p-3 text-sm">{orgInfo.summary}{orgInfo.industry ? ` (${orgInfo.industry})` : ""}</p>}
      <form className="flex gap-2" onSubmit={async (e) => {
        e.preventDefault();
        if (role.trim().length < 2) return;
        setErr(""); setBusy("role");
        try {
          const r = await learner.roleSummary(role.trim());
          setRoleInfo(r);
          onSkills(r.matched.map((s) => s.slug));
        } catch (x) { fail(x); } finally { setBusy(""); }
      }}>
        <input value={role} onChange={(e) => setRole(e.target.value)} maxLength={120} placeholder={t("workRole.rolePh")} aria-label={t("workRole.role")} className={field} />
        <Button type="submit" variant="outline" loading={busy === "role"} disabled={role.trim().length < 2}><BriefcaseBusiness className="h-4 w-4" /> {t("workRole.explain")}</Button>
      </form>
      {roleInfo && (
        <div className="rounded-xl bg-surface-2 p-3 text-sm">
          <p>{roleInfo.summary}</p>
          <p className="mt-1 font-semibold">{t("workRole.keySkills")}: {roleInfo.skills.join(" · ")}</p>
        </div>
      )}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      <p className="text-xs text-muted">{t("workRole.optional")}</p>
    </div>
  );
}
