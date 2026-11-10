import { useTranslation } from "react-i18next";

import { REVIEWED, UI_LANG_NAMES, UI_LANGS, type UiLang } from "@/i18n/languages";

/** Interface language picker: every Indian language we ship; machine-translated ones are labelled. */
export function LanguageSelect({ value, onChange, compact = false }: { value: string; onChange: (v: UiLang) => void; compact?: boolean }) {
  const { t } = useTranslation();
  return (
    <span className="inline-flex flex-col gap-1">
      <select aria-label={t("uiLang.label")} value={value} onChange={(e) => onChange(e.target.value as UiLang)}
        className={compact ? "rounded-full border-2 border-line bg-surface px-2 py-1 text-sm font-semibold" : "rounded-xl border-2 border-line bg-surface px-3 py-2"}>
        {UI_LANGS.map((l) => <option key={l} value={l}>{UI_LANG_NAMES[l]}{REVIEWED.includes(l) ? "" : " (beta)"}</option>)}
      </select>
      {!compact && !REVIEWED.includes(value as UiLang) && <span className="text-xs text-muted">{t("uiLang.machine")}</span>}
    </span>
  );
}
