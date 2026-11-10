import { motion } from "motion/react";

import { flapVariants, shade, useBlink, usePupil, useSvgRef, type CompanionProps } from "./kit";
import { Accessories, Eye, Frame, MoodFx, Outfit } from "./parts";

/** Kili (கிளி): the parrot. */
export function Parrot({ mood, color = "#22c55e", accessories = [], outfit = "none", size = 120, lookAt, mouth }: CompanionProps) {
  const ref = useSvgRef();
  const pupil = usePupil(ref, mood, lookAt);
  const blink = useBlink(mood === "sleepy");
  const dark = shade(color, -45);
  const light = shade(color, 50);
  const talking = mood === "talking";
  const flapping = mood === "cheer" || mood === "celebrate" || mood === "fire";
  const wingL = flapVariants;
  return (
    <Frame svgRef={ref} size={size} mood={mood} label="Kili">
      {/* tail feathers */}
      <path d="M44 92 L30 116 L42 112 L46 118 L52 100z" fill={dark} />
      <path d="M50 96 L44 118 L54 110 L58 118 L58 100z" fill="#2563eb" />

      {/* feet */}
      <path d="M52 100 v8 m-4 0 h8 M66 100 v8 m-4 0 h8" stroke="#f59e0b" strokeWidth="3.5" strokeLinecap="round" />

      {/* body */}
      <ellipse cx="60" cy="66" rx="30" ry="36" fill={color} />
      <ellipse cx="62" cy="76" rx="18" ry="22" fill={light} opacity={0.85} />

      <Outfit outfit={outfit} />

      {/* wing */}
      <motion.path
        d="M34 58 Q22 74 34 92 Q44 84 46 66z"
        fill={dark}
        variants={wingL}
        animate={flapping ? "flap" : mood === "wave" ? "wave" : "rest"}
        style={{ originX: "44px", originY: "60px" }}
      />

      {/* head tuft */}
      <path d="M58 30 Q54 14 62 10 Q60 22 66 28z" fill={dark} />
      <path d="M64 30 Q66 16 76 14 Q68 24 70 30z" fill={color} />

      {/* cheek */}
      <ellipse cx="80" cy="56" rx="6" ry="4" fill="#fb7185" opacity={mood === "hmm" ? 0.2 : 0.55} />

      <Eye mood={mood} dark={dark} pupil={pupil} blink={blink} />

      {/* beak: upper is fixed, lower opens while talking */}
      <path d="M80 50 Q100 50 98 66 Q92 58 80 60z" fill="#ef4444" />
      <motion.path
        d="M81 60 Q92 60 94 66 Q88 70 81 66z"
        fill="#b91c1c"
        animate={
          mouth != null ? { rotate: Math.min(24, mouth * 26) } : talking ? { rotate: [0, 16, 0] } : { rotate: mood === "cheer" ? 18 : 0 }
        }
        transition={mouth != null ? { duration: 0.05 } : talking ? { duration: 0.22, repeat: Infinity } : { duration: 0.2 }}
        style={{ originX: "81px", originY: "62px" }}
      />

      <Accessories accessories={accessories} />
      <MoodFx mood={mood} dark={dark} />
    </Frame>
  );
}
