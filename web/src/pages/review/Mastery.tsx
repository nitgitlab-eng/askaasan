import { Brain } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useCourses } from "@/lib/learn";
import { useMastery, type MasteryGraph } from "@/lib/review";

const LEVEL_COLOR: Record<string, string> = { new: "#d6d3d1", learning: "#fb923c", practicing: "#facc15", mastered: "#22c55e" };

/** Knowledge graph: sections are columns, lessons are nodes sized by mastery. */
function Graph({ g }: { g: MasteryGraph }) {
  const navigate = useNavigate();
  const [hover, setHover] = useState<number | null>(null);
  const layout = useMemo(() => {
    const cols = [...new Set(g.nodes.map((n) => n.section_id))];
    const COL_W = 200, ROW_H = 96, PAD = 110; // PAD leaves room for edge labels
    const byCol: Record<number, number> = {};
    const pos: Record<number, { x: number; y: number }> = {};
    for (const n of g.nodes) {
      const c = cols.indexOf(n.section_id);
      const r = (byCol[c] = (byCol[c] ?? -1) + 1);
      pos[n.id] = { x: PAD + c * COL_W, y: PAD + 30 + r * ROW_H + (c % 2) * 40 };
    }
    const width = PAD * 2 + (cols.length - 1) * COL_W;
    const height = Math.max(...Object.values(pos).map((p) => p.y)) + PAD + 40;
    return { pos, width, height, cols };
  }, [g]);

  return (
    <div className="overflow-x-auto rounded-2xl border border-line bg-surface">
      <svg viewBox={`0 0 ${layout.width} ${layout.height}`} width={Math.max(layout.width, 320)} height={layout.height} role="img" aria-label={g.curriculum.title}>
        {layout.cols.map((sid, c) => {
          const name = g.nodes.find((n) => n.section_id === sid)?.section ?? "";
          return (
            <text key={sid} x={110 + c * 200} y={34} textAnchor="middle" className="fill-[var(--muted)] text-[11px] font-semibold">
              {name.length > 26 ? name.slice(0, 25) + "…" : name}
            </text>
          );
        })}
        {g.edges.map((e) => {
          const a = layout.pos[e.from], b = layout.pos[e.to];
          return <path key={`${e.from}-${e.to}`} d={`M${a.x},${a.y} C${(a.x + b.x) / 2},${a.y} ${(a.x + b.x) / 2},${b.y} ${b.x},${b.y}`} fill="none" stroke="var(--border)" strokeWidth={3} strokeDasharray="6 6" />;
        })}
        {g.nodes.map((n) => {
          const p = layout.pos[n.id];
          const r = 20 + n.mastery * 10;
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`} className="cursor-pointer" onClick={() => navigate(`/learn/${g.curriculum.id}/lesson/${n.id}`)}
              onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} role="link" aria-label={`${n.title}: ${Math.round(n.mastery * 100)}%`}>
              <circle r={r + 6} fill={LEVEL_COLOR[n.level]} opacity={0.25} />
              <circle r={r} fill={LEVEL_COLOR[n.level]} stroke="white" strokeWidth={3} />
              {/* mastery ring */}
              <circle r={r + 3} fill="none" stroke="var(--accent)" strokeWidth={3} strokeDasharray={`${2 * Math.PI * (r + 3) * n.mastery} 999`} transform="rotate(-90)" />
              <text textAnchor="middle" dy="0.35em" className="fill-[#3b2a1a] text-[12px] font-bold">{Math.round(n.mastery * 100)}</text>
              {n.due > 0 && <circle cx={r - 2} cy={-r + 2} r={7} fill="#ef4444" />}
              <text y={r + 18} textAnchor="middle" className={cn("text-[11px]", hover === n.id ? "fill-[var(--accent)] font-bold" : "fill-[var(--text)]")}>
                {n.title.length > 24 ? n.title.slice(0, 23) + "…" : n.title}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export default function MasteryPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: courses } = useCourses();
  const ready = courses?.filter((c) => c.status === "ready") ?? [];
  const cid = Number(id) || ready[0]?.id;
  const { data: g } = useMastery(cid ?? 0);

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-extrabold">{t("mastery.title")}</h1>
          <p className="text-muted">{t("mastery.sub")}</p>
          <p className="text-xs text-muted">{t("mastery.howItWorks")}</p>
        </div>
        {ready.length > 1 && (
          <select value={cid} onChange={(e) => navigate(`/mastery/${e.target.value}`)} className="rounded-xl border-2 border-line bg-surface px-3 py-2" aria-label={t("mastery.course")}>
            {ready.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
        )}
      </header>
      {!cid && (
        <Card className="text-center">
          <Brain className="mx-auto mb-2 h-8 w-8 text-accent" />
          <p>{t("mastery.empty")}</p>
          <Link to="/learn" className="font-semibold text-accent">{t("learn.start")} →</Link>
        </Card>
      )}
      {g && (
        <>
          <Card className="flex flex-wrap items-center gap-6">
            <div>
              <p className="text-sm text-muted">{g.curriculum.title}</p>
              <p className="font-display text-4xl font-extrabold text-accent">{Math.round(g.overall * 100)}%</p>
              <p className="text-sm font-medium">{t("mastery.overall")}</p>
            </div>
            <div className="flex flex-wrap gap-3 text-xs">
              {(["new", "learning", "practicing", "mastered"] as const).map((l) => (
                <span key={l} className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-full" style={{ background: LEVEL_COLOR[l] }} />{t(`mastery.levels.${l}`)}</span>
              ))}
              <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-full bg-red-500" />{t("mastery.dueDot")}</span>
            </div>
          </Card>
          <Graph g={g} />
          {g.nodes.some((n) => n.skills.length > 0) && (
          <Card className="space-y-3">
            <h2 className="font-display text-xl font-bold">{t("mastery.skills")}</h2>
            {g.skills.map((s) => (
              <div key={s.name}>
                <div className="flex justify-between text-sm"><span>{s.name}</span><span className="font-semibold">{Math.round(s.mastery * 100)}%</span></div>
                <div className="h-2.5 overflow-hidden rounded-full bg-surface-2"><div className="h-full rounded-full bg-accent transition-all" style={{ width: `${s.mastery * 100}%` }} /></div>
              </div>
            ))}
          </Card>
          )}
        </>
      )}
    </div>
  );
}
