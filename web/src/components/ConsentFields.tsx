import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { cn } from "@/lib/cn";
import type { ConsentValue } from "@/lib/consent";

/** Terms + age + guardian (DPDP Act: under-18s need a parent's or guardian's consent). */
export function ConsentFields({ value, onChange }: { value: ConsentValue; onChange: (v: ConsentValue) => void }) {
  const { t } = useTranslation();
  const pill = (on: boolean) => cn("flex-1 rounded-xl border-2 px-3 py-2 text-sm font-semibold transition", on ? "border-accent bg-accent/10" : "border-line hover:border-accent");
  return (
    <div className="space-y-3 text-left">
      <fieldset>
        <legend className="mb-1.5 text-sm font-medium">{t("legal.ageQ")}</legend>
        <div className="flex gap-2">
          <button type="button" aria-pressed={value.age_band === "adult"} className={pill(value.age_band === "adult")} onClick={() => onChange({ ...value, age_band: "adult" })}>{t("legal.adult")}</button>
          <button type="button" aria-pressed={value.age_band === "minor"} className={pill(value.age_band === "minor")} onClick={() => onChange({ ...value, age_band: "minor" })}>{t("legal.minor")}</button>
        </div>
      </fieldset>
      {value.age_band === "minor" && (
        <label className="block text-sm">
          <span className="font-medium">{t("legal.guardianEmail")}</span>
          <input type="email" required value={value.guardian_email} onChange={(e) => onChange({ ...value, guardian_email: e.target.value })} className="mt-1 w-full rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent" />
          <span className="mt-1 block text-xs text-muted">{t("legal.guardianNote")}</span>
        </label>
      )}
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" checked={value.accept} onChange={(e) => onChange({ ...value, accept: e.target.checked })} className="mt-1 h-4 w-4 accent-[var(--accent)]" />
        <span>
          {value.age_band === "minor" ? t("legal.agreeMinor") : t("legal.agree")}{" "}
          <Link to="/terms" target="_blank" className="font-semibold text-accent underline">{t("legal.terms")}</Link> {t("legal.and")}{" "}
          <Link to="/privacy" target="_blank" className="font-semibold text-accent underline">{t("legal.privacy")}</Link>.
        </span>
      </label>
    </div>
  );
}
