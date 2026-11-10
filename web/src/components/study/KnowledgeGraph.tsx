import { useState } from "react";
import { useNavigate } from "react-router-dom";

import type { Progress } from "@/lib/study";

/**
 * Skills ↔ lessons network. Skills sit on an inner ring; each lesson sits on the outer ring
 * near the skills it builds. Fill strength = mastery (one hue); the label/legend carries identity.
 */
export function KnowledgeGraph({ graph, labels }: { graph: Progress["graph"]; labels: { skill: string; lesson: string; mastery: string; empty: string } }) {
  const navigate = useNavigate();
  const [hover, setHover] = useState<string | null>(null);
  const skills = graph.nodes.filter((n) => n.type === "skill");
  const lessons = graph.nodes.filter((n) => n.type === "lesson");
  if (!skills.length) return <p className="text-sm text-muted">{labels.empty}</p>;
  const S = 420, C = S / 2, R1 = 90, R2 = 175;
  const pos: Record<string, [number, number]> = {};
  const ang: Record<string, number> = {};
  skills.forEach((s, i) => {
    const a = (2 * Math.PI * i) / skills.length - Math.PI / 2;
    ang[s.id] = a;
    pos[s.id] = [C + R1 * Math.cos(a), C + R1 * Math.sin(a)];
  });
  lessons.forEach((l, i) => {
    const linked = graph.edges.filter((e) => e.from === l.id).map((e) => ang[e.to]).filter((a) => a !== undefined);
    const base = linked.length ? Math.atan2(linked.reduce((s, a) => s + Math.sin(a), 0), linked.reduce((s, a) => s + Math.cos(a), 0)) : (2 * Math.PI * i) / lessons.length;
    const a = base + ((i % 5) - 2) * 0.09; // fan out lessons that share a skill
    pos[l.id] = [C + R2 * Math.cos(a), C + R2 * Math.sin(a)];
  });
  const fill = (m: number | null) => `color-mix(in srgb, var(--accent) ${Math.round(15 + (m ?? 0) * 85)}%, var(--surface))`;
  const near = (id: string) => hover === id || graph.edges.some((e) => (e.from === hover && e.to === id) || (e.to === hover && e.from === id));
  const active = hover ? graph.nodes.find((n) => n.id === hover) : null;
  return (
    <div className="space-y-2">
      <svg viewBox={`0 0 ${S} ${S}`} className="mx-auto w-full max-w-lg" role="img" aria-label={`${labels.skill} / ${labels.lesson}`}>
        {graph.edges.map((e, i) => {
          const a = pos[e.from], b = pos[e.to];
          if (!a || !b) return null;
          const on = hover && (e.from === hover || e.to === hover);
          return <line key={i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={on ? "var(--accent)" : "var(--border)"} strokeWidth={on ? 2 : 1} />;
        })}
        {graph.nodes.map((n) => {
          const p = pos[n.id];
          if (!p) return null;
          const dim = hover && !near(n.id);
          return (
            <g key={n.id} opacity={dim ? 0.3 : 1} onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(n.id)} onBlur={() => setHover(null)}
              onClick={() => n.link && navigate(n.link)} tabIndex={0} role={n.link ? "link" : undefined} aria-label={`${n.label}: ${Math.round((n.mastery ?? 0) * 100)}%`}
              className={n.link ? "cursor-pointer outline-none" : "outline-none"}>
              {n.type === "skill"
                ? <rect x={p[0] - 9} y={p[1] - 9} width={18} height={18} rx={4} fill={fill(n.mastery)} stroke="var(--text)" strokeWidth={1.5} />
                : <circle cx={p[0]} cy={p[1]} r={7} fill={fill(n.mastery)} stroke="var(--surface)" strokeWidth={2} />}
              <circle cx={p[0]} cy={p[1]} r={14} fill="transparent" />
              {n.type === "skill" && <text x={p[0]} y={p[1] + 22} textAnchor="middle" fontSize={10} fill="var(--text)">{n.label.length > 16 ? `${n.label.slice(0, 15)}…` : n.label}</text>}
            </g>
          );
        })}
      </svg>
      <p className="h-5 text-center text-xs text-muted" aria-live="polite">{active && `${active.label} · ${labels.mastery} ${Math.round((active.mastery ?? 0) * 100)}%`}</p>
      <div className="flex justify-center gap-4 text-xs text-muted">
        <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm border-2 border-[var(--text)]" />{labels.skill}</span>
        <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-full bg-accent/60" />{labels.lesson}</span>
        <span>{labels.mastery}: <span className="inline-block h-2 w-10 rounded-full align-middle" style={{ background: "linear-gradient(90deg, color-mix(in srgb, var(--accent) 15%, var(--surface)), var(--accent))" }} /></span>
      </div>
    </div>
  );
}
