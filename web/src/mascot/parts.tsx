import { motion } from "motion/react";
import type { ReactNode, RefObject } from "react";

import { bodyVariants } from "./kit";
import type { MascotMood } from "./store";

/** Eye at (70,46), with blink / happy / thinking states. */
export function Eye({ mood, dark, pupil, blink }: { mood: MascotMood; dark: string; pupil: { x: number; y: number }; blink: boolean }) {
  const eyeOpen = !blink && mood !== "sleepy";
  const happyEyes = mood === "cheer" || mood === "celebrate";
  return (
    <g>
      <ellipse cx="70" cy="46" rx="11" ry={eyeOpen ? 12 : 1.6} fill="#fff" stroke={dark} strokeWidth="1.5" />
      {eyeOpen && !happyEyes && (
        <g>
          <circle cx={71 + pupil.x} cy={47 + pupil.y} r="5.6" fill="#1f1300" />
          <circle cx={73 + pupil.x} cy={44.5 + pupil.y} r="1.8" fill="#fff" />
        </g>
      )}
      {happyEyes && <path d="M62 48 Q70 38 78 48" stroke="#1f1300" strokeWidth="3" fill="none" strokeLinecap="round" />}
      {(mood === "hmm" || mood === "confused") && <path d="M60 32 L78 30" stroke={dark} strokeWidth="2.5" strokeLinecap="round" />}
    </g>
  );
}

export function Outfit({ outfit }: { outfit: string }) {
  return (
    <>
      {/* veshti outfit: white wrap with gold border */}
      {outfit === "veshti" && (
        <g>
          <path d="M33 80 Q60 92 88 80 L86 96 Q60 106 35 96z" fill="#fffdf5" stroke="#e5e7eb" />
          <path d="M35 93 Q60 103 86 93" stroke="#eab308" strokeWidth="3" fill="none" />
        </g>
      )}
      {outfit === "kurta" && (
        <g>
          <path d="M33 72 Q60 84 87 72 L89 98 Q60 108 31 98z" fill="#c026d3" />
          <path d="M60 76 L60 100" stroke="#fde047" strokeWidth="2.5" />
          {[80, 86, 92].map((y) => <circle key={y} cx="60" cy={y} r="1.6" fill="#fde047" />)}
          <path d="M33 92 Q60 104 87 92" stroke="#fde047" strokeWidth="2" fill="none" />
        </g>
      )}
      {outfit === "lab_coat" && (
        <g>
          <path d="M32 70 Q60 82 88 70 L90 100 Q60 110 30 100z" fill="#f8fafc" stroke="#cbd5e1" />
          <path d="M60 74 L54 100 M60 74 L66 100" stroke="#cbd5e1" strokeWidth="1.5" />
          <rect x="68" y="82" width="9" height="7" rx="1.5" fill="#e2e8f0" />
          <path d="M70 80 L70 85 M73 79 L73 85" stroke="#2563eb" strokeWidth="1.5" />
        </g>
      )}
      {outfit === "uniform" && (
        <g>
          <path d="M34 74 Q60 86 86 74 L88 96 Q60 106 32 96z" fill="#1d4ed8" />
          <path d="M54 76 L60 92 L66 76z" fill="#fff" />
          <path d="M58 80 L60 90 L62 80z" fill="#dc2626" />
        </g>
      )}
    </>
  );
}

export function Accessories({ accessories }: { accessories: string[] }) {
  return (
    <>
      {/* accessories */}
      {accessories.includes("glasses") && (
        <g fill="none" stroke="#111827" strokeWidth="2.2">
          <circle cx="70" cy="46" r="13" />
          <path d="M57 44 L44 40" />
        </g>
      )}
      {accessories.includes("cricket_cap") && (
        <g>
          <path d="M44 34 Q60 14 82 30 L84 36 Q62 28 44 38z" fill="#facc15" />
          <path d="M80 32 Q96 32 100 38 L84 37z" fill="#ca8a04" />
        </g>
      )}
      {accessories.includes("headphones") && (
        <g>
          <path d="M46 44 Q58 14 84 34" stroke="#111827" strokeWidth="4" fill="none" strokeLinecap="round" />
          <rect x="40" y="40" width="10" height="16" rx="5" fill="#ef4444" />
        </g>
      )}
      {accessories.includes("grad_cap") && (
        <g>
          <path d="M44 26 L68 16 L92 26 L68 36z" fill="#1f2937" />
          <path d="M56 30 L56 38 Q68 44 80 38 L80 30" fill="#111827" />
          <path d="M88 27 L90 42" stroke="#facc15" strokeWidth="2" />
          <circle cx="90" cy="43" r="2.5" fill="#facc15" />
        </g>
      )}
      {accessories.includes("sunglasses") && (
        <g>
          <rect x="58" y="38" width="24" height="13" rx="6" fill="#111827" />
          <path d="M58 43 L44 39" stroke="#111827" strokeWidth="2.5" />
          <path d="M63 41 L70 41" stroke="#94a3b8" strokeWidth="2" strokeLinecap="round" />
        </g>
      )}
      {accessories.includes("crown") && (
        <g>
          <path d="M50 28 L54 12 L62 22 L68 8 L74 22 L82 12 L86 28z" fill="#facc15" stroke="#ca8a04" strokeWidth="1.5" />
          <circle cx="68" cy="22" r="2.5" fill="#ef4444" />
          <circle cx="58" cy="25" r="1.8" fill="#3b82f6" />
          <circle cx="78" cy="25" r="1.8" fill="#22c55e" />
        </g>
      )}
      {accessories.includes("jasmine") && (
        <g fill="#fff" stroke="#e5e7eb">
          {[0, 1, 2, 3].map((i) => (
            <circle key={i} cx={50 + i * 4} cy={30 - (i % 2) * 3} r="3" />
          ))}
        </g>
      )}

    </>
  );
}

export function MoodFx({ mood, dark }: { mood: MascotMood; dark: string }) {
  const sleepy = mood === "sleepy";
  return (
    <>
      {/* mood props */}
      {mood === "thinking" && (
        <g fill={dark} opacity={0.7}>
          {[0, 1, 2].map((i) => (
            <motion.circle
              key={i}
              cx={96 + i * 7}
              cy={22 - i * 5}
              r={2 + i}
              animate={{ opacity: [0.2, 1, 0.2] }}
              transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.25 }}
            />
          ))}
        </g>
      )}
      {sleepy && (
        <motion.text
          x="88"
          y="26"
          fontSize="14"
          fontWeight="700"
          fill={dark}
          animate={{ y: [26, 14], opacity: [1, 0] }}
          transition={{ duration: 2, repeat: Infinity }}
        >
          z
        </motion.text>
      )}
      {(mood === "cheer" || mood === "celebrate") &&
        [0, 1, 2, 3, 4].map((i) => (
          <motion.circle
            key={i}
            cx={60}
            cy={40}
            r={2.5}
            fill={["#f97316", "#facc15", "#22c55e", "#3b82f6", "#ec4899"][i]}
            animate={{ x: Math.cos(i * 1.3) * 50, y: -30 + Math.sin(i * 1.3) * 30, opacity: [1, 0] }}
            transition={{ duration: 0.9 }}
          />
        ))}
      {mood === "hmm" && (
        <text x="92" y="28" fontSize="18" fontWeight="800" fill={dark}>
          ?
        </text>
      )}
    </>
  );
}

/** Common svg frame: whole-body mood motion + optional streak aura. */
export function Frame({ svgRef, size, mood, label, children }: { svgRef: RefObject<SVGSVGElement | null>; size: number; mood: MascotMood; label: string; children: ReactNode }) {
  return (
    <motion.svg
      ref={svgRef}
      width={size}
      height={size}
      viewBox="0 0 120 120"
      variants={bodyVariants}
      animate={mood}
      style={{ originX: "50%", originY: "90%", overflow: "visible" }}
      role="img"
      aria-label={label}
    >
      {mood === "fire" && (
        <motion.path
          d="M60 8c10 14 30 22 30 48 0 22-14 38-30 38S30 78 30 56C30 30 50 22 60 8z"
          fill="#fb923c"
          opacity={0.35}
          animate={{ scale: [1, 1.1, 1], opacity: [0.25, 0.45, 0.25] }}
          transition={{ duration: 0.5, repeat: Infinity }}
          style={{ originX: "50%", originY: "100%" }}
        />
      )}
      {children}
    </motion.svg>
  );
}

