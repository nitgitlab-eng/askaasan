import type { Variants } from "motion/react";
import { useEffect, useRef, useState, type RefObject } from "react";

import { COMPANIONS, type MascotCharacter } from "./companions";
import type { MascotMood } from "./store";

/** Shared by all companions: same props, same moods, same wardrobe anchor points (eye at 70,46; head top ~y 10–36). */
export interface CompanionProps {
  mood: MascotMood;
  color?: string;
  accessories?: string[];
  outfit?: string;
  size?: number;
  /** Viewport point the eyes should look at; null = look forward. */
  lookAt?: { x: number; y: number } | null;
  /** 0..1 live mouth opening (voice playback); overrides the talking loop. */
  mouth?: number | null;
}

export const bodyVariants: Variants = {
  idle: { y: [0, -3, 0], rotate: 0, transition: { duration: 3, repeat: Infinity, ease: "easeInOut" } },
  watching: { y: 0, rotate: -4, transition: { duration: 0.3 } },
  thinking: { y: [0, -2, 0], rotate: [-3, 3, -3], transition: { duration: 1.6, repeat: Infinity } },
  talking: { y: [0, -2, 0], rotate: 0, transition: { duration: 0.5, repeat: Infinity } },
  cheer: { y: [0, -26, 0, -14, 0], rotate: [0, -8, 8, 0], transition: { duration: 0.9, repeat: 1 } },
  hmm: { rotate: [0, 10, 10, 0], y: 0, transition: { duration: 1.4 } },
  confused: { x: [0, -5, 5, -4, 4, 0], transition: { duration: 0.6 } },
  sleepy: { y: 4, rotate: 6, transition: { duration: 1.2 } },
  fire: { scale: [1, 1.08, 1], transition: { duration: 0.6, repeat: 3 } },
  celebrate: { rotate: [0, 360], y: [0, -30, 0], transition: { duration: 1, repeat: 1 } },
  wave: { rotate: [0, -6, 0], transition: { duration: 0.6, repeat: 2 } },
};


export const flapVariants: Variants = {
  rest: { rotate: 0 },
  flap: { rotate: [0, -35, 0], transition: { duration: 0.25, repeat: 5 } },
  wave: { rotate: [0, -60, -30, -60, 0], transition: { duration: 1.2 } },
};


export function useBlink(disabled: boolean) {
  const [closed, setClosed] = useState(false);
  useEffect(() => {
    if (disabled) return;
    let t: ReturnType<typeof setTimeout>;
    const loop = () => {
      t = setTimeout(() => {
        setClosed(true);
        setTimeout(() => setClosed(false), 140);
        loop();
      }, 2500 + Math.random() * 3500);
    };
    loop();
    return () => clearTimeout(t);
  }, [disabled]);
  return closed;
}


export function shade(hex: string, amt: number) {
  const n = parseInt(hex.slice(1), 16);
  const c = (v: number) => Math.max(0, Math.min(255, v + amt));
  return `#${((c(n >> 16) << 16) | (c((n >> 8) & 255) << 8) | c(n & 255)).toString(16).padStart(6, "0")}`;
}


/** Pupil offset toward a viewport point (eye centre ≈ 58% x / 40% y of the svg box). */
export function usePupil(ref: RefObject<SVGSVGElement | null>, mood: MascotMood, lookAt: CompanionProps["lookAt"]) {
  const [pupil, setPupil] = useState({ x: 0, y: 0 });
  const sleepy = mood === "sleepy";
  useEffect(() => {
    const el = ref.current;
    if (!el || !lookAt || sleepy) {
      setPupil({ x: 0, y: mood === "thinking" ? -2.5 : 0 });
      return;
    }
    const r = el.getBoundingClientRect();
    const dx = lookAt.x - (r.left + r.width * 0.58);
    const dy = lookAt.y - (r.top + r.height * 0.4);
    const d = Math.hypot(dx, dy) || 1;
    const k = Math.min(1, d / 220) * 3.2;
    setPupil({ x: (dx / d) * k, y: (dy / d) * k });
  }, [ref, lookAt, mood, sleepy]);
  return pupil;
}


export const useSvgRef = () => useRef<SVGSVGElement>(null);

/** Each companion's own default colour, from the registry. */
export const COMPANION_COLORS = Object.fromEntries(COMPANIONS.map((c) => [c.id, c.color])) as Record<MascotCharacter, string>;
