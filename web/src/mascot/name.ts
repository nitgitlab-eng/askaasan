import { COMPANIONS, companionOf, isDefaultName, type MascotCharacter } from "./companions";

/** Default companion names; a learner may rename theirs (Personalize). */
export const DEFAULT_NAMES = Object.fromEntries(COMPANIONS.map((c) => [c.id, c.name])) as Record<MascotCharacter, string>;
export const COMPANION_EMOJI = Object.fromEntries(COMPANIONS.map((c) => [c.id, c.emoji])) as Record<MascotCharacter, string>;

/** The companion's name as the interface should show it: a custom name as typed; a default name in the
 * reader's script where we have one (Tamil), otherwise as written. */
export function companionName(character: MascotCharacter | undefined, name: string | undefined, lang: string): string {
  const n = (name ?? "").trim();
  if (!isDefaultName(n)) return n;
  const c = companionOf(character);
  return lang === "ta" ? c.tamil : c.name;
}
