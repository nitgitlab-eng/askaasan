import { motion } from "motion/react";
import { useMemo } from "react";

const RINGS = [6, 12, 18, 24, 30];

/**
 * A kolam that blooms as you learn: every completed lesson draws one petal, ring by ring, around pulli (dots).
 * `slots` is how many petals the full design has (e.g. lessons in a course).
 */
export function Kolam({ filled, slots, size = 220, label }: { filled: number; slots: number; size?: number; label: string }) {
  const petals = useMemo(() => {
    const out: { ring: number; angle: number; ri: number; ro: number }[] = [];
    let left = Math.max(slots, filled, 1);
    RINGS.forEach((n, ring) => {
      if (left <= 0) return;
      const count = ring === RINGS.length - 1 ? left : Math.min(n, left);
      const ri = 8 + ring * 17;
      for (let i = 0; i < count; i++) out.push({ ring, angle: (360 / count) * i + (ring % 2 ? 180 / count : 0), ri, ro: ri + 22 });
      left -= count;
    });
    return out;
  }, [slots, filled]);
  const extent = Math.max(...petals.map((p) => p.ro)) + 8;
  const petal = (ri: number, ro: number, w: number) =>
    `M ${ri} 0 C ${ri + (ro - ri) * 0.35} ${-w} ${ro - (ro - ri) * 0.08} ${-w * 0.55} ${ro} 0 C ${ro - (ro - ri) * 0.08} ${w * 0.55} ${ri + (ro - ri) * 0.35} ${w} ${ri} 0 Z`;
  return (
    <svg viewBox={`${-extent} ${-extent} ${extent * 2} ${extent * 2}`} width={size} height={size} role="img" aria-label={label}>
      {petals.map((p, i) => {
        const done = i < filled;
        const w = Math.min(9, (Math.PI * (p.ri + p.ro)) / (2 * (RINGS[p.ring] ?? 30)) * 0.9);
        return (
          <g key={i} transform={`rotate(${p.angle})`}>
            <motion.path
              d={petal(p.ri, p.ro, w)}
              fill={done ? "color-mix(in srgb, var(--accent) 22%, transparent)" : "none"}
              stroke={done ? "var(--accent)" : "var(--border)"}
              strokeWidth={done ? 1.8 : 1}
              strokeDasharray={done ? undefined : "2 3"}
              strokeLinecap="round"
              initial={done ? { pathLength: 0, opacity: 0 } : false}
              animate={done ? { pathLength: 1, opacity: 1 } : undefined}
              transition={{ duration: 0.6, delay: Math.min(i, 40) * 0.05 }}
            />
            <circle cx={p.ro + 4} cy={0} r={1.6} fill={done ? "var(--accent)" : "var(--muted)"} opacity={done ? 1 : 0.5} />
          </g>
        );
      })}
      <circle r={4} fill="var(--accent)" />
      {[0, 60, 120, 180, 240, 300].map((a) => <circle key={a} r={1.4} cx={Math.cos((a * Math.PI) / 180) * 6} cy={Math.sin((a * Math.PI) / 180) * 6} fill="var(--accent)" />)}
    </svg>
  );
}
