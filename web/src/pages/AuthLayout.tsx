import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { LegalLinks } from "@/components/LegalLinks";
import { SkipLink } from "@/components/SkipLink";
import { StorageNotice } from "@/components/StorageNotice";
import { setLanguage } from "@/i18n";
import { LanguageSelect } from "@/components/LanguageSelect";
import { Kili } from "@/mascot/Kili";
import type { MascotMood } from "@/mascot/store";

export function AuthLayout({ title, sub, mood = "idle", children }: { title: string; sub?: string; mood?: MascotMood; children: ReactNode }) {
  const { i18n } = useTranslation();
  const lang = i18n.language === "en" ? "en" : "ta";
  return (
    <>
      <SkipLink />
      <main id="main" tabIndex={-1} className="mx-auto grid min-h-dvh max-w-5xl items-center gap-8 px-4 py-10 outline-none md:grid-cols-2">
        <section className="hidden flex-col items-center gap-4 text-center md:flex">
          <Kili mood={mood} size={220} />
          <h1 className="font-display text-5xl font-extrabold text-accent">Aasan <span className="text-3xl">· ஆசான்</span></h1>
          <p className="text-lg text-muted">{lang === "ta" ? "AI கற்போம் — உங்கள் மொழியில், உங்கள் துணையுடன்" : "Learn AI your way — in English or Tamil, with a friend by your side"}</p>
        </section>
        <section className="mx-auto w-full max-w-md rounded-3xl border border-line bg-surface p-6 shadow-xl sm:p-8">
          <div className="mb-6 flex items-start justify-between gap-4">
            <div>
              <div className="mb-2 md:hidden">
                <Kili mood={mood} size={72} />
              </div>
              <h2 className="font-display text-2xl font-bold">{title}</h2>
              {sub && <p className="text-muted">{sub}</p>}
            </div>
            <LanguageSelect compact value={lang} onChange={(v) => setLanguage(v)} />
          </div>
          {children}
          <LegalLinks className="mt-6" />
        </section>
        <StorageNotice />
      </main>
    </>
  );
}
