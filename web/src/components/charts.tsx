/**
 * Minimal, theme-aware SVG charts (dataviz method: one axis, thin marks, 4px rounded
 * data ends, 2px gaps, recessive grid, hover tooltip, table fallback, text in ink
 * tokens — never in series colour). Colours come from CSS vars so all 6 themes work.
 */
import { Table2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { cn } from "@/lib/cn";

function ChartFrame({ title, children, table }: { title: string; children: ReactNode; table: ReactNode }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <figure className="space-y-2">
      <figcaption className="flex items-center justify-between">
        <span className="font-display text-base font-bold">{title}</span>
        <button onClick={() => setAsTable(!asTable)} aria-pressed={asTable} className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-muted hover:bg-surface-2">
          <Table2 className="h-3.5 w-3.5" /> {asTable ? "Chart" : "Table"}
        </button>
      </figcaption>
      {asTable ? <div className="max-h-64 overflow-auto rounded-xl border border-line text-sm">{table}</div> : children}
    </figure>
  );
}

function SimpleTable({ head, rows }: { head: [string, string]; rows: [string, string | number][] }) {
  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-surface-2 text-left text-xs text-muted"><tr><th className="px-3 py-1.5">{head[0]}</th><th className="px-3 py-1.5 text-right">{head[1]}</th></tr></thead>
      <tbody>{rows.map(([a, b]) => <tr key={a} className="border-t border-line"><td className="px-3 py-1.5">{a}</td><td className="px-3 py-1.5 text-right tabular-nums">{b}</td></tr>)}</tbody>
    </table>
  );
}

/** Vertical bars over time — one series, accent hue, crosshair-style hover. */
export function TimeBars({ title, data, valueLabel, format = (v) => String(v) }: {
  title: string;
  data: { label: string; value: number }[];
  valueLabel: string;
  format?: (v: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 600, H = 160, PAD_L = 32, PAD_B = 22, PAD_T = 8;
  const max = Math.max(1, ...data.map((d) => d.value));
  const nice = Math.pow(10, Math.floor(Math.log10(max)));
  const top = Math.ceil(max / nice) * nice;
  const bw = (W - PAD_L) / data.length;
  const y = (v: number) => PAD_T + (H - PAD_B - PAD_T) * (1 - v / top);
  return (
    <ChartFrame title={title} table={<SimpleTable head={["", valueLabel]} rows={data.map((d) => [d.label, format(d.value)])} />}>
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${title}: ${data.length} points`}>
          {[0, 0.5, 1].filter((f) => Number.isInteger(top * f)).map((f) => (
            <g key={f}>
              <line x1={PAD_L} x2={W} y1={y(top * f)} y2={y(top * f)} stroke="var(--border)" strokeWidth={1} />
              <text x={PAD_L - 6} y={y(top * f) + 4} textAnchor="end" className="fill-[var(--muted)] text-[10px] tabular-nums">{format(top * f)}</text>
            </g>
          ))}
          {data.map((d, i) => {
            const x = PAD_L + i * bw + 1;
            const h = Math.max(d.value ? 2 : 0, H - PAD_B - y(d.value));
            const w = Math.max(1, bw - 2); // 2px surface gap between bars
            const r = Math.min(4, w / 2, h);
            return (
              <g key={d.label} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                <rect x={PAD_L + i * bw} y={0} width={bw} height={H - PAD_B} fill="transparent" />
                {h > 0 && (
                  <path
                    d={`M${x},${H - PAD_B} v${-(h - r)} q0,${-r} ${r},${-r} h${w - 2 * r} q${r},0 ${r},${r} v${h - r} z`}
                    fill="var(--accent)" opacity={hover === null || hover === i ? 1 : 0.45}
                  />
                )}
                {(i === 0 || i === data.length - 1 || i % 7 === 0) && (
                  <text x={x + w / 2} y={H - 6} textAnchor="middle" className="fill-[var(--muted)] text-[10px]">{d.label}</text>
                )}
              </g>
            );
          })}
        </svg>
        {hover !== null && (
          <div className="pointer-events-none absolute -top-2 rounded-lg border border-line bg-surface px-2 py-1 text-xs shadow"
            style={{ left: `${((PAD_L + hover * bw + bw / 2) / W) * 100}%`, transform: "translateX(-50%)" }}>
            <b className="tabular-nums">{format(data[hover].value)}</b> {valueLabel} · {data[hover].label}
          </div>
        )}
      </div>
    </ChartFrame>
  );
}

/** Horizontal magnitude bars with direct value labels (0..max). */
export function HBars({ title, data, max, format = (v) => String(v), valueLabel, empty }: {
  title: string;
  data: { label: string; value: number; note?: string }[];
  max?: number;
  format?: (v: number) => string;
  valueLabel: string;
  empty?: string;
}) {
  const top = max ?? Math.max(1, ...data.map((d) => d.value));
  return (
    <ChartFrame title={title} table={<SimpleTable head={["", valueLabel]} rows={data.map((d) => [d.label, format(d.value)])} />}>
      {data.length === 0 ? <p className="text-sm text-muted">{empty}</p> : (
        <ul className="space-y-2">
          {data.map((d) => (
            <li key={d.label} className="group" title={`${d.label}: ${format(d.value)}${d.note ? ` · ${d.note}` : ""}`}>
              <div className="flex justify-between gap-2 text-sm">
                <span className="truncate">{d.label}</span>
                <span className="shrink-0 font-semibold tabular-nums">{format(d.value)}</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-surface-2">
                <div className="h-full rounded-full bg-accent transition-[width] group-hover:brightness-110" style={{ width: `${Math.min(100, (100 * d.value) / top)}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </ChartFrame>
  );
}

/** NPS: hero number + diverging stacked bar (detractors red · passives neutral · promoters blue). */
export function NpsBar({ title, distribution, nps }: { title: string; distribution: Record<string, number>; nps: number | undefined }) {
  const counts = { d: 0, p: 0, pr: 0 };
  for (const [k, v] of Object.entries(distribution)) {
    const n = Number(k);
    if (n <= 6) counts.d += v;
    else if (n <= 8) counts.p += v;
    else counts.pr += v;
  }
  const total = counts.d + counts.p + counts.pr || 1;
  const segs = [
    { key: "d", label: "Detractors (0–6)", n: counts.d, cls: "nps-neg" },
    { key: "p", label: "Passives (7–8)", n: counts.p, cls: "nps-mid" },
    { key: "pr", label: "Promoters (9–10)", n: counts.pr, cls: "nps-pos" },
  ];
  return (
    <ChartFrame title={title} table={<SimpleTable head={["", "count"]} rows={segs.map((s) => [s.label, s.n])} />}>
      <div className="flex items-center gap-4">
        <p className="font-display text-4xl font-extrabold tabular-nums">{nps ?? "—"}</p>
        <div className="flex-1 space-y-2">
          <div className="flex h-4 gap-[2px] overflow-hidden rounded-full">
            {segs.filter((s) => s.n).map((s) => <div key={s.key} className={cn("h-full", s.cls)} style={{ width: `${(100 * s.n) / total}%` }} title={`${s.label}: ${s.n}`} />)}
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-muted">
            {segs.map((s) => <span key={s.key} className="flex items-center gap-1"><span className={cn("h-2.5 w-2.5 rounded-full", s.cls)} />{s.label} · {s.n}</span>)}
          </div>
        </div>
      </div>
    </ChartFrame>
  );
}

/**
 * Radar: "you" (accent fill) vs "required" (ink dashed outline), levels 0..max.
 * Two series → always a legend; identity also carried by line style, not colour alone.
 */
export function Radar({ title, axes, max = 4, labels }: {
  title: string;
  axes: { label: string; value: number; target: number }[];
  max?: number;
  labels: { you: string; target: string; skill: string };
}) {
  const [hover, setHover] = useState<number | null>(null);
  const S = 280, C = S / 2, R = 96;
  const n = Math.max(axes.length, 3);
  const pt = (i: number, v: number) => {
    const a = (Math.PI * 2 * i) / n - Math.PI / 2;
    const r = (R * Math.min(v, max)) / max;
    return [C + r * Math.cos(a), C + r * Math.sin(a)] as const;
  };
  const poly = (k: "value" | "target") => axes.map((x, i) => pt(i, x[k]).join(",")).join(" ");
  const table = (
    <table className="w-full">
      <thead className="sticky top-0 bg-surface-2 text-left text-xs text-muted"><tr><th className="px-3 py-1.5">{labels.skill}</th><th className="px-3 py-1.5 text-right">{labels.you}</th><th className="px-3 py-1.5 text-right">{labels.target}</th></tr></thead>
      <tbody>{axes.map((x) => <tr key={x.label} className="border-t border-line"><td className="px-3 py-1.5">{x.label}</td><td className="px-3 py-1.5 text-right tabular-nums">{x.value}</td><td className="px-3 py-1.5 text-right tabular-nums">{x.target}</td></tr>)}</tbody>
    </table>
  );
  return (
    <ChartFrame title={title} table={table}>
      <div className="flex flex-col items-center gap-2">
        <svg viewBox={`-80 -12 ${S + 160} ${S + 24}`} className="w-full max-w-md" role="img" aria-label={title}>
          {Array.from({ length: max }, (_, k) => (
            <polygon key={k} points={axes.map((_, i) => pt(i, k + 1).join(",")).join(" ")} fill="none" stroke="var(--border)" strokeWidth={1} />
          ))}
          {axes.map((_, i) => { const [x, y] = pt(i, max); return <line key={i} x1={C} y1={C} x2={x} y2={y} stroke="var(--border)" strokeWidth={1} />; })}
          <polygon points={poly("target")} fill="none" stroke="var(--text)" strokeWidth={2} strokeDasharray="5 4" opacity={0.7} />
          <polygon points={poly("value")} fill="var(--accent)" fillOpacity={0.25} stroke="var(--accent)" strokeWidth={2} />
          {axes.map((x, i) => {
            const [px, py] = pt(i, x.value);
            const [lx, ly] = pt(i, max + 0.9);
            return (
              <g key={x.label} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                <circle cx={px} cy={py} r={hover === i ? 6 : 4} fill="var(--accent)" stroke="var(--surface)" strokeWidth={2} />
                <circle cx={px} cy={py} r={14} fill="transparent" />
                <text x={lx} y={ly} textAnchor={lx < C - 4 ? "end" : lx > C + 4 ? "start" : "middle"} dominantBaseline="middle" fontSize={10} fill="var(--muted)">
                  {x.label.length > 18 ? `${x.label.slice(0, 17)}…` : x.label}
                </text>
              </g>
            );
          })}
        </svg>
        <p className="h-5 text-xs text-muted" aria-live="polite">{hover !== null && `${axes[hover].label}: ${labels.you} ${axes[hover].value} / ${labels.target} ${axes[hover].target}`}</p>
        <div className="flex gap-4 text-xs">
          <span className="flex items-center gap-1.5"><span className="h-2.5 w-4 rounded-sm bg-accent/40 ring-2 ring-accent" />{labels.you}</span>
          <span className="flex items-center gap-1.5"><svg width="18" height="6" aria-hidden><line x1="0" y1="3" x2="18" y2="3" stroke="var(--text)" strokeWidth="2" strokeDasharray="5 4" /></svg>{labels.target}</span>
        </div>
      </div>
    </ChartFrame>
  );
}
