import type { Lang } from "./engines";

/**
 * Short spoken lines so a call never goes silent: one while Aasan searches the web, or one when its first words are
 * slow. Spoken in the voice's language (which can differ from the screen's), never saved into the reply.
 * `think` lines stay neutral so they also fit role-play characters and workshop hosts.
 */
export const FILLERS: Record<Lang, { search: string[]; think: string[] }> = {
  en: {
    search: ["One moment, let me look that up.", "Let me check the latest on that.", "Give me a second, I'm checking that online."],
    think: ["Hmm, let me think.", "Good question, give me a second.", "Okay, one moment."],
  },
  ta: {
    search: ["ஒரு நிமிஷம், பார்த்துச் சொல்கிறேன்.", "இப்போதைய தகவலைப் பார்க்கிறேன்.", "ஒரு நொடி, இணையத்தில் பார்க்கிறேன்."],
    think: ["ம்ம், யோசிக்கிறேன்.", "நல்ல கேள்வி, ஒரு நொடி.", "சரி, ஒரு நிமிஷம்."],
  },
};

/** No first word this long after the turn went out: say a thinking line. */
export const THINK_FILLER_MS = 1800;

/** "all": searching and thinking lines. "think": only the neutral thinking line. "none": stay quiet. */
export type FillerKind = "all" | "think" | "none";

export function pickFiller(lang: Lang, kind: "search" | "think", rand: () => number = Math.random): string {
  const lines = FILLERS[lang]?.[kind] ?? FILLERS.en[kind];
  return lines[Math.floor(rand() * lines.length) % lines.length];
}
