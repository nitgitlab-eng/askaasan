import { useTranslation } from "react-i18next";

import { cn } from "@/lib/cn";
import type { Preferences } from "@/lib/types";
import { COMPANIONS, effectiveColor, isDefaultName, type MascotCharacter } from "@/mascot/companions";
import { Kili } from "@/mascot/Kili";
import { COMPANION_COLORS } from "@/mascot/kit";
import { mascot } from "@/mascot/store";

type MascotPrefs = Preferences["mascot"];

/**
 * Pick a companion from the registry (onboarding and Personalize). New companions in companions.ts show up here
 * automatically. A renamed companion keeps its custom name and a colour the learner chose survives the switch;
 * default names and colours follow the new companion.
 */
export function CompanionPicker({ prefs, onPick, size = 64 }: { prefs: MascotPrefs; onPick: (patch: Partial<MascotPrefs>) => void; size?: number }) {
  const { t } = useTranslation();
  const customColor = effectiveColor(prefs.character, prefs.color) !== COMPANION_COLORS[prefs.character];
  const colorFor = (c: MascotCharacter) => (customColor || c === prefs.character ? prefs.color : COMPANION_COLORS[c]);
  const label = (c: (typeof COMPANIONS)[number]) => t(`personalize.companions.${c.id}`, { defaultValue: c.name });

  return (
    <div role="radiogroup" aria-label={t("personalize.companion")} className="grid grid-cols-[repeat(auto-fill,minmax(6.5rem,1fr))] gap-2">
      {COMPANIONS.map((c) => (
        <button
          key={c.id}
          type="button"
          role="radio"
          aria-checked={prefs.character === c.id}
          onClick={() => {
            if (c.id === prefs.character) return;
            onPick({ character: c.id, color: colorFor(c.id), name: isDefaultName(prefs.name) ? label(c) : prefs.name });
            mascot.react("wave");
          }}
          className={cn(
            "flex flex-col items-center rounded-2xl border-2 p-2 text-center transition",
            prefs.character === c.id ? "border-accent bg-accent/10" : "border-line hover:border-accent",
          )}
        >
          <Kili character={c.id} mood="idle" size={size} color={colorFor(c.id)} />
          <span className="text-sm font-semibold">{label(c)}</span>
          <span className="text-[11px] text-muted">{t(`personalize.companionsSub.${c.id}`, { defaultValue: c.blurb })}</span>
        </button>
      ))}
    </div>
  );
}
