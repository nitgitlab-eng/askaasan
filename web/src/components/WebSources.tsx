import { Globe } from "lucide-react";
import { useTranslation } from "react-i18next";

import { isWebSource, type Citation } from "@/lib/citations";

/** The web pages a reply used, as small links under it. Built from the server's search results only. */
export function WebSources({ citations }: { citations?: Citation[] }) {
  const { t } = useTranslation();
  const web = (citations ?? []).filter(isWebSource).filter((s) => /^https?:\/\//i.test(s.url));
  if (!web.length) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5" aria-label={t("mentor.web.sources")}>
      <span className="flex items-center gap-1 text-xs text-muted"><Globe size={12} aria-hidden /> {t("mentor.web.sources")}</span>
      {web.map((s) => (
        <a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer nofollow" title={s.url}
          className="max-w-[16rem] truncate rounded-full border border-line px-2 py-0.5 text-xs hover:border-accent">
          {s.title || hostOf(s.url)}
        </a>
      ))}
    </div>
  );
}

function hostOf(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
