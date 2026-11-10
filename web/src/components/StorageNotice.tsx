import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

const KEY = "aasan-storage-notice";

/** We only use essential storage, so this is a notice rather than a consent prompt. */
export function StorageNotice() {
  const { t } = useTranslation();
  const [seen, setSeen] = useState(() => {
    try {
      return localStorage.getItem(KEY) === "1";
    } catch {
      return true;
    }
  });
  if (seen) return null;
  const close = () => {
    try {
      localStorage.setItem(KEY, "1");
    } catch {
      /* private mode: just hide for this visit */
    }
    setSeen(true);
  };
  return (
    // Top of the screen, not the bottom: at the bottom it covered chat inputs (Ask Aasan's message box, the workshop
    // Tap-to-talk bar) for every new user until they pressed "Got it".
    <div role="region" aria-label={t("legal.storageLabel")} className="fixed inset-x-3 top-[64px] z-40 mx-auto flex max-w-xl flex-wrap items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-3 text-sm shadow-lg md:top-[76px]">
      <p className="min-w-0 flex-1">{t("legal.storage")} <Link to="/privacy" className="font-semibold text-accent underline">{t("legal.privacy")}</Link></p>
      <button onClick={close} className="rounded-xl bg-accent px-4 py-1.5 font-semibold text-accent-ink">{t("legal.ok")}</button>
    </div>
  );
}
