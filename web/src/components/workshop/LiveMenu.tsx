import { Hand, X } from "lucide-react";
import { useId, useRef } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { Session, WorkshopMsg } from "@/lib/workshops";

import { Transcript } from "./Caption";
import { StageList } from "./StageRail";
import { useDialogFocus } from "./useDialogFocus";

function Switch({ label, hint, checked, onChange, disabled }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  const hintId = useId();
  return (
    <div className="flex items-start gap-3">
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{label}</p>
        {hint && <p id={hintId} className="text-sm text-muted">{hint}</p>}
      </div>
      <button type="button" role="switch" aria-checked={checked} aria-label={label} aria-describedby={hint ? hintId : undefined} disabled={disabled} onClick={() => onChange(!checked)}
        className={cn("relative h-8 min-h-8 w-14 shrink-0 rounded-full border-2 transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40 disabled:opacity-50",
          checked ? "border-accent bg-accent" : "border-line bg-surface-2")}>
        <span className={cn("absolute top-0.5 h-6 w-6 rounded-full bg-surface shadow transition-all", checked ? "left-[1.6rem]" : "left-0.5")} />
      </button>
    </div>
  );
}

export interface LiveMenuProps {
  session: Session;
  messages: WorkshopMsg[];
  language: "en" | "ta";
  handsFree: boolean;
  sound: boolean;
  handRaised: boolean;
  online: boolean;
  onClose: () => void;
  onRaiseHand: () => void;
  onLanguage: (l: "en" | "ta") => void;
  onHandsFree: (v: boolean) => void;
  onSound: (v: boolean) => void;
}

/** The ⋮ sheet: workshop plan, transcript, raise hand, language and the hands-free switch. */
export function LiveMenu(p: LiveMenuProps) {
  const { t } = useTranslation();
  const panel = useRef<HTMLDivElement>(null);
  useDialogFocus(panel, p.onClose);
  const section = "space-y-2 border-t-2 border-line pt-4";
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={p.onClose}>
      <div ref={panel} role="dialog" aria-modal="true" aria-label={t("workshop.live.menu")} onClick={(e) => e.stopPropagation()}
        className="h-full w-full max-w-md space-y-4 overflow-y-auto bg-bg p-4 shadow-xl">
        <div className="flex items-center justify-between gap-2">
          <p className="font-display text-xl font-bold">{t("workshop.live.menu")}</p>
          <Button variant="ghost" className="min-h-11 min-w-11 px-2.5" onClick={p.onClose} aria-label={t("workshop.live.close")}><X className="h-5 w-5" aria-hidden /></Button>
        </div>

        <div>
          <Button variant="outline" className="min-h-11 w-full" onClick={p.onRaiseHand} disabled={!p.online}>
            <Hand className="h-5 w-5" aria-hidden /> {t("workshop.raiseHand")}
          </Button>
          {p.handRaised && <p role="status" className="mt-2 text-sm font-medium text-good">{t("workshop.handRaised")}</p>}
        </div>

        <nav aria-label={t("workshop.live.plan")} className={section}>
          <h2 className="font-display text-lg font-bold">{t("workshop.live.plan")}</h2>
          <StageList session={p.session} />
        </nav>

        <div className={section}>
          <h2 className="font-display text-lg font-bold">{t("workshop.live.language")}</h2>
          <div role="radiogroup" aria-label={t("workshop.live.language")} className="grid grid-cols-2 gap-2">
            {(["en", "ta"] as const).map((l) => (
              <button key={l} type="button" role="radio" aria-checked={p.language === l} disabled={!p.online} onClick={() => p.onLanguage(l)} lang={l}
                className={cn("min-h-11 rounded-xl border-2 px-3 font-semibold transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40 disabled:opacity-50",
                  p.language === l ? "border-accent bg-accent/10" : "border-line hover:border-accent")}>
                {l === "en" ? "English" : "தமிழ்"}
              </button>
            ))}
          </div>
        </div>

        <div className={cn(section, "space-y-4")}>
          <Switch label={t("workshop.live.handsFree")} hint={t("workshop.live.handsFreeHint")} checked={p.handsFree} onChange={p.onHandsFree} />
          <Switch label={t("workshop.live.sound")} checked={p.sound} onChange={p.onSound} />
        </div>

        <details className={section}>
          <summary className="min-h-11 cursor-pointer py-2 font-display text-lg font-bold">{t("workshop.live.transcript")}</summary>
          <Transcript messages={p.messages} />
        </details>
      </div>
    </div>
  );
}
