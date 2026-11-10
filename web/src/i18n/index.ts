import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./en";
import { isUiLang, type UiLang } from "./languages";
import ta from "./ta";

// Machine-translated languages are separate chunks, fetched only when chosen (en.json is the export source, not a locale).
const bundles = import.meta.glob<{ default: Record<string, unknown> }>(["./locales/*.json", "!./locales/en.json"]);

const stored = (() => {
  try {
    return localStorage.getItem("aasan-lang");
  } catch {
    return null;
  }
})();

void i18n.use(initReactI18next).init({
  resources: { ta: { translation: ta }, en: { translation: en } },
  lng: stored === "ta" ? "ta" : "en", // English-first; others load on demand below
  fallbackLng: "en",
  // {{mascot}} in any string = the learner's own companion (Kili / Mayil / Yaanai or the name they gave it).
  interpolation: { escapeValue: false, defaultVariables: { mascot: "Kili" } },
  returnObjects: true,
});

async function ensure(lng: UiLang): Promise<boolean> {
  if (lng === "en" || lng === "ta" || i18n.hasResourceBundle(lng, "translation")) return true;
  const load = bundles[`./locales/${lng}.json`];
  if (!load) return false; // not generated yet → stay on the fallback
  i18n.addResourceBundle(lng, "translation", (await load()).default, true, true);
  return true;
}

export function setLanguage(lng: string) {
  const want: UiLang = isUiLang(lng) ? lng : "en";
  void ensure(want).then((ok) => {
    const use = ok ? want : "en";
    void i18n.changeLanguage(use);
    document.documentElement.lang = use;
  });
  try {
    localStorage.setItem("aasan-lang", want);
  } catch {
    /* storage unavailable */
  }
}

if (stored && stored !== "en" && stored !== "ta") setLanguage(stored);

/** Called whenever the learner's companion or language changes; re-renders translated text. */
export function setMascotName(name: string) {
  const vars = (i18n.options.interpolation ??= {}).defaultVariables ??= {};
  if (vars.mascot === name) return;
  vars.mascot = name;
  void i18n.changeLanguage(i18n.language); // nudge react-i18next to re-render
}

export default i18n;
