import type { ComponentType } from "react";

import type { MascotCharacter } from "./companions";
import { Elephant } from "./Elephant";
import type { CompanionProps } from "./kit";
import { Parrot } from "./Parrot";
import { Peacock } from "./Peacock";

/** Artwork per companion. Keyed by the registry (companions.ts), so adding a companion there fails the build until its art is added here. */
export const COMPANION_ART: Record<MascotCharacter, ComponentType<CompanionProps>> = {
  kili: Parrot,
  yaanai: Elephant,
  mayil: Peacock,
};
