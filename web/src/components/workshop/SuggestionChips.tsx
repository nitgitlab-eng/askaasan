import { useTranslation } from "react-i18next";

import { cn } from "@/lib/cn";
import type { Chip } from "@/lib/workshops";

/**
 * The 2–3 replies the host offers right now (from the server's `suggest`). Tapping one is the same as saying it, and
 * works while the host is still talking (the server stops that reply politely). Disabled only while one is being sent.
 */
export function SuggestionChips({ chips, disabled, onChip }: { chips: Chip[]; disabled?: boolean; onChip: (c: Chip) => void }) {
  const { t } = useTranslation();
  if (!chips.length) return null;
  return (
    <div role="group" aria-label={t("workshop.live.chipsLabel")} className="flex flex-wrap justify-center gap-2" data-testid="chips">
      {chips.map((c, i) => (
        <button key={c} type="button" onClick={() => onChip(c)} disabled={disabled}
          className={cn(
            "min-h-11 rounded-full border-2 px-5 py-2 text-base font-semibold transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40 disabled:opacity-50",
            i === 0 ? "border-accent bg-accent text-accent-ink hover:brightness-105" : "border-line bg-surface hover:border-accent",
          )}>
          {t(`workshop.chips.${c}`)}
        </button>
      ))}
    </div>
  );
}
