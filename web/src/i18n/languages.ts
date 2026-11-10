/** Interface languages. English and Tamil are written and reviewed by hand; the others are machine-translated from
 * English (api: `manage.py translate_ui`) and marked for review until a native speaker signs them off. */
export const UI_LANGS = ["en", "ta", "hi", "te", "kn", "ml", "bn", "mr", "gu"] as const;
export type UiLang = (typeof UI_LANGS)[number];
export const UI_LANG_NAMES: Record<UiLang, string> = {
  en: "English", ta: "தமிழ்", hi: "हिन्दी", te: "తెలుగు", kn: "ಕನ್ನಡ", ml: "മലയാളം", bn: "বাংলা", mr: "मराठी", gu: "ગુજરાતી",
};
/** Move a code here once its translation has been reviewed. */
export const REVIEWED: readonly UiLang[] = ["en", "ta"];
export const isUiLang = (x: unknown): x is UiLang => typeof x === "string" && (UI_LANGS as readonly string[]).includes(x);
/** BCP-47 locale for dates and numbers. */
export const localeOf = (lang: string) => `${isUiLang(lang) ? lang : "en"}-IN`;
