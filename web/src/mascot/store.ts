import { create } from "zustand";

import type { MascotCharacter } from "./companions";

export type MascotMood =
  | "idle"
  | "watching" // learner is typing
  | "thinking" // LLM is working
  | "talking" // tokens are streaming
  | "cheer" // correct answer
  | "hmm" // wrong answer / gentle confusion
  | "confused" // error
  | "sleepy" // learner inactive
  | "fire" // streak
  | "celebrate" // milestone
  | "wave"; // hello / goodbye

export type { MascotCharacter } from "./companions";

export interface MascotLook {
  color?: string;
  outfit?: string;
  accessories?: string[];
}

export interface Bubble {
  id: number;
  text: string;
  actions?: { label: string; onClick: () => void }[];
}

interface MascotState {
  mood: MascotMood;
  bubble: Bubble | null;
  pointTarget: DOMRect | null;
  minimized: boolean;
  /** 0..1 beak opening driven by real audio; null = use the talking loop. */
  mouth: number | null;
  character: MascotCharacter;
  setCharacter: (c: MascotCharacter) => void;
  /** The learner's chosen look (Personalize); every <Kili> wears it unless told otherwise. */
  look: MascotLook;
  setLook: (look: MascotLook) => void;
  /** Set a mood; transient moods fall back to `idle` after `ms`. */
  react: (mood: MascotMood, ms?: number) => void;
  say: (text: string, opts?: { ms?: number; actions?: Bubble["actions"] }) => void;
  hush: () => void;
  pointAt: (el: Element | null) => void;
  setMinimized: (v: boolean) => void;
}

let moodTimer: ReturnType<typeof setTimeout> | undefined;
let bubbleTimer: ReturnType<typeof setTimeout> | undefined;
let bubbleSeq = 0;

export const TRANSIENT_MS: Partial<Record<MascotMood, number>> = {
  cheer: 2200,
  hmm: 2600,
  confused: 3000,
  celebrate: 3500,
  wave: 2000,
  fire: 3000,
};

export const useMascot = create<MascotState>((set) => ({
  mood: "idle",
  bubble: null,
  pointTarget: null,
  minimized: false,
  mouth: null,
  character: "kili",
  setCharacter: (character) => set({ character }),
  look: {},
  setLook: (look) => set({ look }),
  react: (mood, ms) => {
    clearTimeout(moodTimer);
    set({ mood });
    const ttl = ms ?? TRANSIENT_MS[mood];
    if (ttl) moodTimer = setTimeout(() => set({ mood: "idle" }), ttl);
  },
  say: (text, opts) => {
    clearTimeout(bubbleTimer);
    set({ bubble: { id: ++bubbleSeq, text, actions: opts?.actions }, minimized: false });
    const ms = opts?.ms ?? Math.min(9000, 2500 + text.length * 45);
    if (ms > 0) bubbleTimer = setTimeout(() => set({ bubble: null }), ms);
  },
  hush: () => {
    clearTimeout(bubbleTimer);
    set({ bubble: null });
  },
  pointAt: (el) => set({ pointTarget: el ? el.getBoundingClientRect() : null }),
  setMinimized: (minimized) => set({ minimized }),
}));

/** Imperative handle for non-React code (WS handlers, quiz engines…). */
export const mascot = {
  react: (m: MascotMood, ms?: number) => useMascot.getState().react(m, ms),
  say: (t: string, o?: Parameters<MascotState["say"]>[1]) => useMascot.getState().say(t, o),
  hush: () => useMascot.getState().hush(),
  pointAt: (el: Element | null) => useMascot.getState().pointAt(el),
};
