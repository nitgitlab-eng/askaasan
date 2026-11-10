/**
 * The companion registry: every companion a learner can pick lives here, and every screen reads this list
 * (onboarding, Personalize, the dock, the lesson tutor toggle, names in any script).
 *
 * To add a companion:
 *  1. add an entry below (id is stored in preferences, so keep it short, lowercase and never rename it);
 *  2. add its artwork to COMPANION_ART in art.ts (TypeScript fails the build until you do);
 *  3. add the same id to COMPANIONS in api/apps/accounts/companions.py (a test checks both lists match);
 *  4. optional: translated names/descriptions under personalize.companions.<id> / companionsSub.<id> —
 *     without them the English name and blurb below are shown.
 */
export const COMPANIONS = [
  { id: "kili", name: "Kili", tamil: "கிளி", emoji: "🦜", color: "#22c55e", blurb: "Chatty parrot · quick, catchy lines" },
  { id: "yaanai", name: "Yaanai", tamil: "யானை", emoji: "🐘", color: "#8b9bb4", blurb: "Wise elephant · never forgets" },
  { id: "mayil", name: "Mayil", tamil: "மயில்", emoji: "🦚", color: "#2563eb", blurb: "Colourful peacock · vivid stories" },
] as const;

export type Companion = (typeof COMPANIONS)[number];
export type MascotCharacter = Companion["id"];

export const DEFAULT_CHARACTER: MascotCharacter = "kili";
export const COMPANION_IDS = COMPANIONS.map((c) => c.id) as MascotCharacter[];

const BY_ID = Object.fromEntries(COMPANIONS.map((c) => [c.id, c])) as Record<MascotCharacter, Companion>;

/** The registry entry for an id; unknown or missing ids (e.g. a companion that was removed) fall back to the default. */
export function companionOf(id: string | undefined | null): Companion {
  return (id && BY_ID[id as MascotCharacter]) || BY_ID[DEFAULT_CHARACTER];
}

/** The colour a companion is actually drawn in: Kili's default green looks odd on other companions, so it falls back to their own colour. */
export function effectiveColor(id: string | undefined | null, color: string | undefined | null): string {
  const c = companionOf(id);
  const kiliGreen = BY_ID[DEFAULT_CHARACTER].color;
  return !color || (c.id !== DEFAULT_CHARACTER && color === kiliGreen) ? c.color : color;
}

/** Colour swatches for a companion: its own colour first, then the shared palette (no duplicates). */
export function swatchesFor(id: string | undefined | null, palette: readonly string[]): string[] {
  return [...new Set([companionOf(id).color, ...palette])];
}

/** True when `name` is one of the companions' built-in names (any script), i.e. the learner never renamed it. */
export function isDefaultName(name: string | undefined | null): boolean {
  const n = (name ?? "").trim().toLowerCase();
  return !n || COMPANIONS.some((c) => c.name.toLowerCase() === n || c.tamil === n);
}
