import { ChevronLeft, ChevronRight, Dices, ExternalLink, Mic, MicOff, RotateCcw, Volume2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { listenOnce, speakAndWait, stopSpeaking } from "@/voice/oneShot";

import { ChoiceBody } from "./bodies";
import { compile } from "./safeMath";
import type { BodyProps } from "./types";

// ── Narrated slides (+ question) ──────────────────────────────────────

export function SlidesBody(props: BodyProps<{ selected?: number[] }>) {
  const { t } = useTranslation();
  const slides = props.payload.slides as { title: string; text: string }[];
  const [i, setI] = useState(0);
  const [seenAll, setSeenAll] = useState(!!props.result);
  const go = (n: number) => {
    stopSpeaking();
    setI(n);
    if (n === slides.length - 1) setSeenAll(true);
  };
  const narrate = () => {
    stopSpeaking();
    void speakAndWait(`${slides[i].title}. ${slides[i].text}`);
  };
  return (
    <div className="space-y-4">
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-accent/20 via-surface to-surface-2 p-6 text-center">
        <p className="text-xs font-semibold text-muted">{i + 1} / {slides.length}</p>
        <h4 className="mt-1 font-display text-2xl font-bold">{slides[i].title}</h4>
        <p className="mx-auto mt-2 max-w-md text-lg">{slides[i].text}</p>
        <div className="mt-4 flex items-center justify-center gap-2">
          <button onClick={() => go(i - 1)} disabled={i === 0} aria-label={t("lesson.prev")} className="rounded-full border-2 border-line bg-surface p-2 disabled:opacity-40"><ChevronLeft className="h-5 w-5" /></button>
          <button onClick={narrate} className="flex items-center gap-1 rounded-full bg-accent px-3 py-2 text-sm font-semibold text-accent-ink"><Volume2 className="h-4 w-4" /> {t("lesson.listen")}</button>
          <button onClick={() => go(i + 1)} disabled={i === slides.length - 1} aria-label={t("lesson.nextSlide")} className="rounded-full border-2 border-line bg-surface p-2 disabled:opacity-40"><ChevronRight className="h-5 w-5" /></button>
        </div>
        <div className="mt-3 flex justify-center gap-1.5">{slides.map((_, k) => <span key={k} className={cn("h-1.5 w-6 rounded-full", k <= i ? "bg-accent" : "bg-line")} />)}</div>
      </div>
      {seenAll ? <ChoiceBody {...props} /> : <p className="text-center text-sm text-muted">{t("lesson.watchFirst")}</p>}
    </div>
  );
}

// ── Concept map: choose the relationship for each link ────────────────

export function ConceptMapBody({ payload, answer, setAnswer, result, locked }: BodyProps<{ labels?: Record<string, string> }>) {
  const { t } = useTranslation();
  const labels = answer.labels ?? {};
  const per: Record<string, boolean> | undefined = result?.reveal.per_link;
  const links = payload.links as { id: string; source: string; target: string }[];
  const nodes = useMemo(() => [...new Set(links.flatMap((l) => [l.source, l.target]))], [links]);
  const W = 640, H = 340;
  const pos = useMemo(() => Object.fromEntries(nodes.map((n, k) => {
    const a = (2 * Math.PI * k) / nodes.length - Math.PI / 2;
    return [n, { x: W / 2 + Math.cos(a) * 225, y: H / 2 + Math.sin(a) * 125 }];
  })), [nodes]);
  // Two-line labels so long concept names aren't cut off.
  const wrap = (s: string): [string, string] => {
    if (s.length <= 18) return [s, ""];
    const cut = s.lastIndexOf(" ", 18) > 6 ? s.lastIndexOf(" ", 18) : 18;
    const rest = s.slice(cut).trim();
    return [s.slice(0, cut), rest.length > 18 ? rest.slice(0, 17) + "…" : rest];
  };
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-2xl bg-surface-2 p-2">
        <svg viewBox={`0 0 ${W} ${H}`} className="mx-auto w-full max-w-2xl" role="img" aria-label={t("lesson.types.concept_map")}>
          <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10z" fill="var(--muted)" /></marker></defs>
          {links.map((l) => {
            const a = pos[l.source], b = pos[l.target];
            const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
            return (
              <g key={l.id}>
                <line x1={a.x} y1={a.y} x2={b.x - (b.x - a.x) * 0.18} y2={b.y - (b.y - a.y) * 0.18} stroke={per ? (per[l.id] ? "#16a34a" : "#dc2626") : "var(--muted)"} strokeWidth={2.5} markerEnd="url(#arr)" />
                <rect x={mx - 46} y={my - 11} width={92} height={22} rx={11} fill="var(--surface)" stroke="var(--border)" />
                <text x={mx} y={my + 4} textAnchor="middle" className="fill-[var(--text)] text-[10px] font-semibold">{labels[l.id] ? labels[l.id].slice(0, 16) : "?"}</text>
              </g>
            );
          })}
          {nodes.map((n) => (
            <g key={n} transform={`translate(${pos[n].x},${pos[n].y})`}>
              <title>{n}</title>
              <rect x={-74} y={wrap(n)[1] ? -22 : -16} width={148} height={wrap(n)[1] ? 44 : 32} rx={16} fill="var(--accent)" />
              <text textAnchor="middle" y={wrap(n)[1] ? -4 : 4} className="fill-white text-[11px] font-bold">{wrap(n)[0]}</text>
              {wrap(n)[1] && <text textAnchor="middle" y={11} className="fill-white text-[11px] font-bold">{wrap(n)[1]}</text>}
            </g>
          ))}
        </svg>
      </div>
      <div className="grid gap-2">
        {links.map((l) => (
          <label key={l.id} className="flex flex-wrap items-center gap-2 text-sm">
            <b>{l.source}</b>
            <select disabled={locked} value={labels[l.id] ?? ""} onChange={(e) => setAnswer({ labels: { ...labels, [l.id]: e.target.value } })}
              className={cn("rounded-lg border-2 bg-surface px-2 py-1", per ? (per[l.id] ? "border-good" : "border-bad") : "border-line")} aria-label={`${l.source} → ${l.target}`}>
              <option value="">— {t("lesson.pickRelation")} —</option>
              {(payload.labels as string[]).map((x) => <option key={x} value={x}>{x}</option>)}
            </select>
            <span>→ <b>{l.target}</b></span>
            {per && !per[l.id] && <span className="text-good">({result?.reveal.labels?.[l.id]})</span>}
          </label>
        ))}
      </div>
    </div>
  );
}

// ── Interactive visualization (function plot / probability simulator) ─

interface VizSpec {
  kind: "function_plot" | "probability_sim";
  expression: string;
  x_min: number;
  x_max: number;
  params: { name: string; min: number; max: number; step: number; value: number }[];
  sides: number;
}

function FunctionPlot({ spec }: { spec: VizSpec }) {
  const [vals, setVals] = useState<Record<string, number>>(() => Object.fromEntries(spec.params.map((p) => [p.name, p.value])));
  const f = useMemo(() => {
    try {
      return compile(spec.expression.replace(/\*\*/g, "^"), ["x", ...spec.params.map((p) => p.name)]);
    } catch {
      return null;
    }
  }, [spec]);
  if (!f) return <p className="text-sm text-bad">⚠️ {spec.expression}</p>;
  const W = 480, H = 220, N = 120;
  const xs = Array.from({ length: N + 1 }, (_, k) => spec.x_min + ((spec.x_max - spec.x_min) * k) / N);
  const ys = xs.map((x) => f({ ...vals, x })).map((y) => (Number.isFinite(y) ? y : NaN));
  const finite = ys.filter(Number.isFinite);
  const lo = Math.min(0, ...finite), hi = Math.max(1, ...finite);
  const sx = (x: number) => ((x - spec.x_min) / (spec.x_max - spec.x_min)) * W;
  const sy = (y: number) => H - ((y - lo) / (hi - lo || 1)) * H;
  const d = xs.map((x, k) => (Number.isFinite(ys[k]) ? `${k ? "L" : "M"}${sx(x).toFixed(1)},${sy(ys[k]).toFixed(1)}` : "")).join(" ");
  return (
    <div className="space-y-3">
      <svg viewBox={`-10 -10 ${W + 20} ${H + 20}`} className="w-full rounded-xl bg-surface-2" role="img" aria-label={spec.expression}>
        <line x1={0} y1={sy(0)} x2={W} y2={sy(0)} stroke="var(--border)" />
        <line x1={sx(Math.max(spec.x_min, Math.min(0, spec.x_max)))} y1={0} x2={sx(Math.max(spec.x_min, Math.min(0, spec.x_max)))} y2={H} stroke="var(--border)" />
        <path d={d} fill="none" stroke="var(--accent)" strokeWidth={3} strokeLinejoin="round" />
        <text x={6} y={14} className="fill-[var(--muted)] text-[11px]">y = {spec.expression}</text>
      </svg>
      {spec.params.map((p) => (
        <label key={p.name} className="flex items-center gap-3 text-sm">
          <b className="w-6">{p.name}</b>
          <input type="range" min={p.min} max={p.max} step={p.step} value={vals[p.name]} onChange={(e) => setVals({ ...vals, [p.name]: Number(e.target.value) })} className="flex-1 accent-[var(--accent)]" />
          <span className="w-12 text-right font-mono">{vals[p.name]}</span>
        </label>
      ))}
    </div>
  );
}

function ProbabilitySim({ sides }: { sides: number }) {
  const { t } = useTranslation();
  const [counts, setCounts] = useState<number[]>(() => Array(sides).fill(0));
  const total = counts.reduce((a, b) => a + b, 0);
  const roll = (n: number) => {
    const next = [...counts];
    // Runs in a click handler, not during render.
    // eslint-disable-next-line react/purity
    for (let k = 0; k < n; k++) next[Math.floor(Math.random() * sides)]++;
    setCounts(next);
  };
  const label = (k: number) => (sides === 2 ? [t("lesson.heads"), t("lesson.tails")][k] : String(k + 1));
  return (
    <div className="space-y-3">
      <div className="flex h-40 items-end gap-2 rounded-xl bg-surface-2 p-3">
        {counts.map((c, k) => (
          <div key={k} className="flex flex-1 flex-col items-center gap-1">
            <span className="text-xs font-semibold">{total ? Math.round((100 * c) / total) : 0}%</span>
            <div className="w-full rounded-t-lg bg-accent transition-all" style={{ height: `${total ? (100 * c) / Math.max(...counts) : 0}%`, minHeight: 2 }} />
            <span className="text-xs">{label(k)}</span>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {[1, 10, 100, 1000].map((n) => <button key={n} onClick={() => roll(n)} className="flex items-center gap-1 rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent"><Dices className="h-4 w-4" /> ×{n}</button>)}
        <button onClick={() => setCounts(Array(sides).fill(0))} className="flex items-center gap-1 rounded-xl px-3 py-1.5 text-sm text-muted"><RotateCcw className="h-4 w-4" /> {t("lesson.reset")}</button>
        <span className="self-center text-sm text-muted">{t("lesson.trials", { count: total })}</span>
      </div>
    </div>
  );
}

export function VizBody(props: BodyProps<{ selected?: number[] }>) {
  const spec = props.payload.viz as VizSpec;
  return (
    <div className="space-y-4">
      {spec.kind === "probability_sim" ? <ProbabilitySim sides={spec.sides === 6 ? 6 : 2} /> : <FunctionPlot spec={spec} />}
      <ChoiceBody {...props} />
    </div>
  );
}

// ── Decision tree (branching story) ───────────────────────────────────

/** 🎙 Voice mode for stories: Kili reads the scene and options aloud, the learner answers by speaking. */
function StoryVoice({ scene, choices, onChoose }: { scene: string; choices: string[]; onChoose: (i: number) => void }) {
  const { t, i18n } = useTranslation();
  const [on, setOn] = useState(() => sessionStorage.getItem("aasan-story-voice") === "1");
  const [state, setState] = useState<"idle" | "speaking" | "listening" | "matching">("idle");
  const [heard, setHeard] = useState("");
  const [err, setErr] = useState("");
  const lang = i18n.language === "ta" ? "ta" : "en";
  useEffect(() => {
    if (!on) return;
    let cancelled = false;
    (async () => {
      setErr("");
      for (let attempt = 0; attempt < 2 && !cancelled; attempt++) {
        setState("speaking");
        const opts = choices.map((c, i) => t("lesson.voiceOption", { n: i + 1, text: c })).join(". ");
        await speakAndWait(attempt === 0 ? `${scene}. ${opts}` : t("lesson.voiceAgain"));
        if (cancelled) return;
        setState("listening");
        let said = "";
        try {
          said = await listenOnce(lang);
        } catch {
          setErr(t("mentor.voice.errors.mic_denied"));
          break;
        }
        if (cancelled) return;
        setHeard(said);
        if (!said) continue;
        setState("matching");
        const r = await api<{ index: number | null }>("/api/learn/match-choice/", { method: "POST", json: { spoken: said, options: choices } }).catch(() => ({ index: null }));
        if (cancelled) return;
        if (r.index !== null && r.index !== undefined) {
          onChoose(r.index);
          return;
        }
      }
      setState("idle");
    })();
    return () => {
      cancelled = true;
      stopSpeaking();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [on, scene]);
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <button type="button" aria-pressed={on} onClick={() => { const v = !on; setOn(v); sessionStorage.setItem("aasan-story-voice", v ? "1" : "0"); if (!v) stopSpeaking(); }}
        className={cn("flex items-center gap-1.5 rounded-full border-2 px-3 py-1 font-semibold", on ? "border-accent bg-accent/10" : "border-line")}>
        {on ? <Mic className="h-4 w-4 text-accent" /> : <MicOff className="h-4 w-4" />} {t("lesson.voiceMode")}
      </button>
      {on && state !== "idle" && <span className="text-muted">{t(`lesson.voiceState.${state}`)}</span>}
      {on && heard && <span className="italic text-muted">“{heard}”</span>}
      {err && <span className="text-bad">{err}</span>}
    </div>
  );
}

export function DecisionTreeBody({ payload, answer, setAnswer, result, locked }: BodyProps<{ path?: string[] }>) {
  const { t } = useTranslation();
  const nodes = payload.nodes as Record<string, { text: string; choices: { id: string; text: string; next: string }[] }>;
  const path = answer.path ?? [];
  const steps: { node: string; chose?: string }[] = [];
  let node: string | "" = payload.start;
  for (const cid of path) {
    const c = nodes[node]?.choices.find((x) => x.id === cid);
    steps.push({ node, chose: c?.text });
    node = c?.next ?? "";
  }
  const ended = path.length > 0 && !node;
  return (
    <div className="space-y-3">
      {!locked && !ended && node && (
        <StoryVoice
          key={node}
          scene={nodes[node].text}
          choices={nodes[node].choices.map((c) => c.text)}
          onChoose={(i) => setAnswer({ path: [...path, nodes[node].choices[i].id] })}
        />
      )}
      {steps.map((s, k) => (
        <div key={k} className="space-y-1">
          <p className="rounded-2xl rounded-tl-sm bg-surface-2 px-4 py-2">{nodes[s.node].text}</p>
          <p className="ml-auto w-fit rounded-2xl rounded-tr-sm bg-accent px-4 py-2 text-accent-ink">{s.chose}</p>
        </div>
      ))}
      {!ended && node && (
        <div className="space-y-2">
          <p className="rounded-2xl rounded-tl-sm bg-surface-2 px-4 py-2">{nodes[node].text}</p>
          <div className="grid gap-2">
            {nodes[node].choices.map((c) => (
              <button key={c.id} disabled={locked} onClick={() => setAnswer({ path: [...path, c.id] })}
                className="rounded-xl border-2 border-line bg-surface px-4 py-2.5 text-left font-medium hover:border-accent">{c.text}</button>
            ))}
          </div>
        </div>
      )}
      {ended && !result && <p className="text-sm text-muted">🏁 {t("lesson.storyEnded")}</p>}
      {path.length > 0 && !locked && (
        <button onClick={() => setAnswer({ path: [] })} className="flex items-center gap-1 text-sm text-muted hover:text-accent"><RotateCcw className="h-4 w-4" /> {t("lesson.restartStory")}</button>
      )}
    </div>
  );
}

// ── Real-world task ───────────────────────────────────────────────────

export function TaskBody({ payload, answer, setAnswer, locked }: BodyProps<{ text?: string }>) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3">
      <ol className="list-decimal space-y-1 pl-5">{(payload.steps as string[]).map((s) => <li key={s}>{s}</li>)}</ol>
      {payload.link && (
        <a href={payload.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent">
          <ExternalLink className="h-4 w-4" /> {new URL(payload.link).hostname}
        </a>
      )}
      <textarea value={answer.text ?? ""} disabled={locked} onChange={(e) => setAnswer({ text: e.target.value })} rows={5}
        placeholder={t("lesson.taskPaste")} aria-label={t("lesson.taskPaste")}
        className="w-full rounded-xl border-2 border-line bg-surface p-3 outline-none focus:border-accent" />
    </div>
  );
}
