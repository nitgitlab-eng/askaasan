import { motion, type Variants } from "motion/react";

import { shade, useBlink, usePupil, useSvgRef, type CompanionProps } from "./kit";
import { Accessories, Eye, Frame, MoodFx, Outfit } from "./parts";

/** An elephant ear fans out and lifts a little; the birds' wing flap (up to -60°) swung it down across the body. */
const earVariants: Variants = {
  rest: { rotate: 0, scaleX: 1 },
  flap: { rotate: [0, 10, 0], scaleX: [1, 1.18, 1], transition: { duration: 0.3, repeat: 4 } },
  wave: { rotate: [0, 16, 6, 16, 0], scaleX: [1, 1.2, 1.1, 1.2, 1], transition: { duration: 1.2 } },
};

/** Yaanai (யானை): the gentle elephant. Ears flap where Kili flaps wings; the trunk does the talking. */
export function Elephant({ mood, color = "#8b9bb4", accessories = [], outfit = "none", size = 120, lookAt, mouth }: CompanionProps) {
  const ref = useSvgRef();
  const pupil = usePupil(ref, mood, lookAt);
  const blink = useBlink(mood === "sleepy");
  const dark = shade(color, -40);
  const light = shade(color, 35);
  const talking = mood === "talking";
  const trumpet = mood === "cheer" || mood === "celebrate" || mood === "fire";
  const flapping = trumpet || mood === "wave";
  const trunk = mouth != null ? { rotate: -Math.min(30, mouth * 34) } : trumpet ? { rotate: [0, -40, -33, -40, 0] } : talking ? { rotate: [0, -12, 0] } : mood === "sleepy" ? { rotate: 8 } : { rotate: [0, 4, 0] };
  const trunkT = mouth != null ? { duration: 0.05 } : trumpet ? { duration: 1.2 } : talking ? { duration: 0.35, repeat: Infinity } : { duration: 3, repeat: Infinity };
  return (
    <Frame svgRef={ref} size={size} mood={mood} label="Yaanai">
      {/* tail */}
      <path d="M28 76 Q18 82 22 92" stroke={dark} strokeWidth="3" fill="none" strokeLinecap="round" />
      <circle cx="22" cy="93" r="3" fill={dark} />
      {/* legs */}
      {[38, 50, 64, 76].map((x, i) => (
        <g key={x}>
          <rect x={x - 6} y="88" width="12" height="20" rx="5" fill={i % 2 ? color : dark} />
          {[x - 3, x + 1].map((cx) => <circle key={cx} cx={cx + 1} cy="106" r="1.6" fill={light} />)}
        </g>
      ))}
      {/* body */}
      <ellipse cx="56" cy="78" rx="32" ry="22" fill={color} />
      <ellipse cx="54" cy="86" rx="20" ry="10" fill={light} opacity={0.5} />
      <Outfit outfit={outfit} />
      {/* ear (flaps), drawn behind the head so it joins at the back of the head */}
      <motion.g variants={earVariants} animate={flapping ? (mood === "wave" ? "wave" : "flap") : "rest"} style={{ transformBox: "view-box", originX: "56px", originY: "42px" }}>
        <path d="M58 30 Q30 24 32 52 Q34 74 56 64 Q62 48 58 30z" fill={dark} />
        <path d="M54 36 Q38 34 39 52 Q41 64 54 59 Q57 48 54 36z" fill="#f9a8d4" opacity={0.55} />
      </motion.g>
      {/* head: the shared eye sits in its upper half, leaving the front of the face for the trunk */}
      <circle cx="72" cy="50" r="25" fill={color} />
      {/* hair tuft */}
      <path d="M68 27 Q66 20 70 17 M73 26 Q74 19 78 17 M77 27 Q81 22 85 22" stroke={dark} strokeWidth="2" fill="none" strokeLinecap="round" />
      <ellipse cx="62" cy="64" rx="5" ry="3.5" fill="#fb7185" opacity={mood === "hmm" ? 0.2 : 0.5} />
      <Eye mood={mood} dark={dark} pupil={pupil} blink={blink} />
      {/* mouth opens under the trunk while talking */}
      <motion.ellipse cx="79" cy="73" rx="4.5" fill="#7f1d1d" animate={{ ry: mouth != null ? 0.5 + mouth * 4 : talking ? [0.6, 3.5, 0.6] : trumpet ? 3 : 0.6 }} transition={mouth != null ? { duration: 0.05 } : { duration: 0.3, repeat: talking ? Infinity : 0 }} />
      {/* tusk, from the side of the trunk */}
      <path d="M85 66 Q94 69 96 76 Q89 74 84 70z" fill="#fffbeb" stroke="#e7e5e4" strokeWidth="0.8" />
      {/* trunk grows from the front of the face, below the eye. Pivots are in viewBox units (view-box), not the
          group's own box, or the raised trunk swings off the head. */}
      <motion.g animate={trunk} transition={trunkT} style={{ transformBox: "view-box", originX: "89px", originY: "54px" }}>
        <path d="M89 54 Q99 62 98 76 Q97 86 105 88" stroke={color} strokeWidth="10" fill="none" strokeLinecap="round" />
        <path d="M93 60 L99 61 M96 69 L101 69 M96 78 L101 77" stroke={dark} strokeWidth="1.2" strokeLinecap="round" opacity={0.35} />
      </motion.g>
      <Accessories accessories={accessories} />
      <MoodFx mood={mood} dark={dark} />
    </Frame>
  );
}
