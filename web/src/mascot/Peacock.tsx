import { motion } from "motion/react";

import { flapVariants, shade, useBlink, usePupil, useSvgRef, type CompanionProps } from "./kit";
import { Accessories, Eye, Frame, MoodFx, Outfit } from "./parts";

const FEATHERS = [-70, -48, -26, -4, 18, 40, 62];

/** Mayil (மயில்): the peacock. The tail fans open to celebrate. */
export function Peacock({ mood, color = "#2563eb", accessories = [], outfit = "none", size = 120, lookAt, mouth }: CompanionProps) {
  const ref = useSvgRef();
  const pupil = usePupil(ref, mood, lookAt);
  const blink = useBlink(mood === "sleepy");
  const dark = shade(color, -45);
  const light = shade(color, 45);
  const talking = mood === "talking";
  const show = mood === "cheer" || mood === "celebrate" || mood === "fire" || mood === "wave";
  const fan = show ? { scale: [0.7, 1.08, 1], opacity: 1 } : mood === "sleepy" ? { scale: 0.45, opacity: 0.6 } : { scale: 0.72, opacity: 0.9 };
  return (
    <Frame svgRef={ref} size={size} mood={mood} label="Mayil">
      {/* tail fan */}
      <motion.g animate={fan} transition={{ duration: show ? 0.7 : 0.4 }} style={{ originX: "52px", originY: "86px" }}>
        {FEATHERS.map((a) => (
          <g key={a} transform={`rotate(${a} 52 86)`}>
            <path d="M52 86 Q48 50 52 22 Q56 50 52 86z" fill="#15803d" />
            <ellipse cx="52" cy="26" rx="7" ry="9" fill="#16a34a" />
            <ellipse cx="52" cy="26" rx="4.4" ry="5.8" fill="#eab308" />
            <ellipse cx="52" cy="26.5" rx="2.6" ry="3.4" fill={dark} />
          </g>
        ))}
      </motion.g>
      {/* legs */}
      <path d="M54 98 v10 m-4 0 h8 M64 98 v10 m-4 0 h8" stroke="#a8a29e" strokeWidth="3" strokeLinecap="round" />
      {/* body */}
      <ellipse cx="58" cy="80" rx="22" ry="22" fill={color} />
      <ellipse cx="62" cy="86" rx="12" ry="12" fill={light} opacity={0.45} />
      <Outfit outfit={outfit} />
      {/* wing */}
      <motion.path d="M42 72 Q32 86 42 100 Q52 94 54 78z" fill="#0f766e" variants={flapVariants} animate={show ? (mood === "wave" ? "wave" : "flap") : "rest"} style={{ originX: "50px", originY: "74px" }} />
      {/* neck + head */}
      <path d="M50 70 Q50 50 60 38 L80 40 Q70 52 70 70z" fill={color} />
      <circle cx="70" cy="44" r="17" fill={color} />
      {/* crest */}
      {[[-14, 0], [0, -2], [14, 0]].map(([dx, dy]) => (
        <g key={dx}>
          <path d={`M70 28 L${70 + dx} ${10 + dy}`} stroke={dark} strokeWidth="1.5" />
          <circle cx={70 + dx} cy={9 + dy} r="3" fill="#14b8a6" />
          <circle cx={70 + dx} cy={9 + dy} r="1.4" fill="#eab308" />
        </g>
      ))}
      <ellipse cx="80" cy="56" rx="5" ry="3" fill="#fb7185" opacity={mood === "hmm" ? 0.2 : 0.45} />
      <Eye mood={mood} dark={dark} pupil={pupil} blink={blink} />
      {/* beak */}
      <path d="M84 44 L97 48 L84 51z" fill="#d97706" />
      <motion.path
        d="M84 51 L95 50 L84 55z"
        fill="#b45309"
        animate={mouth != null ? { rotate: Math.min(22, mouth * 24) } : talking ? { rotate: [0, 14, 0] } : { rotate: mood === "cheer" ? 16 : 0 }}
        transition={mouth != null ? { duration: 0.05 } : talking ? { duration: 0.22, repeat: Infinity } : { duration: 0.2 }}
        style={{ originX: "84px", originY: "51px" }}
      />
      <Accessories accessories={accessories} />
      <MoodFx mood={mood} dark={dark} />
    </Frame>
  );
}
