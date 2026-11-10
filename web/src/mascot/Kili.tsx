import { COMPANION_ART } from "./art";
import { companionOf, effectiveColor, type MascotCharacter } from "./companions";
import type { CompanionProps } from "./kit";
import { useMascot } from "./store";

export type KiliProps = CompanionProps & { character?: MascotCharacter };

const NO_ACCESSORIES: string[] = [];

/**
 * The learner's companion, whichever one they picked from the registry (companions.ts).
 * Every screen renders <Kili …/>; which companion appears, its colour and its outfit follow the learner's choice in Personalize.
 * Passing `character` previews another companion, so the learner's own look is not applied to it.
 */
export function Kili({ character, color, outfit, accessories, ...rest }: KiliProps) {
  const chosen = useMascot((s) => s.character);
  const look = useMascot((s) => s.look);
  const who = companionOf(character ?? chosen).id;
  const own = !character || character === chosen;
  color ??= own ? look.color : undefined;
  outfit ??= own ? look.outfit : undefined;
  accessories ??= own ? (look.accessories ?? NO_ACCESSORIES) : undefined;
  const props = { ...rest, color: effectiveColor(who, color), outfit, accessories };
  const Art = COMPANION_ART[who];
  return <Art {...props} />;
}
