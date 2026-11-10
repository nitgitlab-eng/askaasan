import "leaflet/dist/leaflet.css";

import L from "leaflet";
import { Camera, CheckCircle2, ExternalLink, MapPin, MessagesSquare, Play } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { fileToDataUrl } from "@/lib/imageFile";
import { roleplay, type RolePlayResult, type Session } from "@/lib/roleplay";

import { InlineRolePlay } from "./InlineRolePlay";
import type { BodyProps } from "./types";

// ── Map: find each place on a real map ────────────────────────────────

/** Per-item verdict when we have it; after a reload only the overall result is known, so don't paint right answers red. */
function markColor(per: number | undefined, result: BodyProps["result"]): string {
  if (!result) return "#f97316";
  if (per === undefined) return result.correct ? "#16a34a" : "#f97316";
  return per >= 1 ? "#16a34a" : "#dc2626";
}

const VIEW: Record<string, [number, number, number]> = { india: [22.5, 80, 4], tamil_nadu: [11, 78.4, 6], world: [20, 10, 2] };
type LatLon = { lat: number; lon: number };
const dot = (color: string, label: string) =>
  L.divIcon({ className: "", html: `<div style="background:${color};color:#fff;border:2px solid #fff;border-radius:999px;min-width:22px;height:22px;padding:0 5px;display:flex;align-items:center;justify-content:center;font:700 12px system-ui;box-shadow:0 1px 4px #0006">${label}</div>`, iconSize: [22, 22], iconAnchor: [11, 11] });

export function MapBody({ payload, answer, setAnswer, result, locked }: BodyProps<{ points?: Record<string, LatLon> }>) {
  const { t } = useTranslation();
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const targets = payload.targets as { id: string; name: string; hint: string }[];
  const [active, setActive] = useState(targets[0]?.id);
  const pts = useMemo(() => answer.points ?? {}, [answer.points]);
  const st = useRef({ active, pts, locked, setAnswer });
  useEffect(() => {
    st.current = { active, pts, locked, setAnswer };
  });

  useEffect(() => {
    if (!el.current || map.current) return;
    const [lat, lon, z] = VIEW[payload.region] ?? VIEW.india;
    const m = L.map(el.current, { worldCopyJump: true }).setView([lat, lon], z);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 12, attribution: "© OpenStreetMap contributors" }).addTo(m);
    m.on("click", (e: L.LeafletMouseEvent) => {
      const s = st.current;
      if (s.locked || !s.active) return;
      const next = { ...s.pts, [s.active]: { lat: e.latlng.lat, lon: ((e.latlng.lng + 540) % 360) - 180 } };
      s.setAnswer({ points: next });
      const left = targets.find((x) => !next[x.id]);
      if (left) setActive(left.id);
    });
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
  }, [payload.region, targets]);

  useEffect(() => {
    const g = layer.current;
    if (!g) return;
    g.clearLayers();
    targets.forEach((tg, i) => {
      const p = pts[tg.id];
      if (p) L.marker([p.lat, p.lon], { icon: dot(markColor(result?.reveal?.per_place?.[tg.id], result), String(i + 1)) }).addTo(g);
      const truth = result?.reveal?.places?.[tg.id];
      if (truth) {
        const tip = document.createElement("span");
        tip.textContent = truth.name; // creator text: never parsed as HTML
        L.marker([truth.lat, truth.lon], { icon: dot("#2563eb", "✓") }).bindTooltip(tip).addTo(g);
        if (p) L.polyline([[p.lat, p.lon], [truth.lat, truth.lon]], { color: "#2563eb", dashArray: "4 6", weight: 2 }).addTo(g);
      }
    });
  }, [pts, result, targets]);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={t("act.map.pick")}>
        {targets.map((tg, i) => (
          <button key={tg.id} type="button" role="radio" aria-checked={active === tg.id} disabled={locked} onClick={() => setActive(tg.id)}
            className={cn("flex items-center gap-1.5 rounded-full border-2 px-3 py-1 text-sm", active === tg.id ? "border-accent bg-accent/10" : "border-line", pts[tg.id] && "font-semibold")}>
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent text-[11px] font-bold text-accent-ink">{i + 1}</span>
            {tg.name}{pts[tg.id] && <MapPin className="h-3.5 w-3.5 text-accent" />}
            {result?.reveal?.km?.[tg.id] != null && <span className="text-xs text-muted">· {t("act.map.off", { km: result.reveal.km[tg.id] })}</span>}
          </button>
        ))}
      </div>
      {!locked && active && <p className="text-sm text-muted">{t("act.map.tap", { name: targets.find((x) => x.id === active)?.name })}{targets.find((x) => x.id === active)?.hint && ` (${targets.find((x) => x.id === active)?.hint})`}</p>}
      <div ref={el} className="h-80 w-full overflow-hidden rounded-2xl border-2 border-line" role="application" aria-label={t("act.map.label")} />
    </div>
  );
}

// ── Image hotspot: put each label in the right place on a picture ─────

export function HotspotBody({ payload, answer, setAnswer, result, locked }: BodyProps<{ points?: Record<string, { x: number; y: number }> }>) {
  const { t } = useTranslation();
  const labels = payload.labels as { id: string; label: string }[];
  const [active, setActive] = useState(labels[0]?.id);
  const pts = answer.points ?? {};
  const targets = result?.reveal?.targets as Record<string, { x: number; y: number; r: number }> | undefined;
  const place = (e: React.MouseEvent<HTMLDivElement>) => {
    if (locked || !active) return;
    const r = e.currentTarget.getBoundingClientRect();
    const next = { ...pts, [active]: { x: ((e.clientX - r.left) / r.width) * 100, y: ((e.clientY - r.top) / r.height) * 100 } };
    setAnswer({ points: next });
    const left = labels.find((l) => !next[l.id]);
    if (left) setActive(left.id);
  };
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {labels.map((l, i) => (
          <button key={l.id} type="button" aria-pressed={active === l.id} disabled={locked} onClick={() => setActive(l.id)}
            className={cn("flex items-center gap-1.5 rounded-full border-2 px-3 py-1 text-sm", active === l.id ? "border-accent bg-accent/10" : "border-line")}>
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent text-[11px] font-bold text-accent-ink">{i + 1}</span>{l.label}
          </button>
        ))}
      </div>
      <div className="relative cursor-crosshair select-none overflow-hidden rounded-2xl border-2 border-line" onClick={place} role="application" aria-label={t("act.hotspot.label")}>
        <img src={payload.image} alt="" className="block w-full" draggable={false} />
        {targets && Object.entries(targets).map(([id, tg]) => (
          <span key={`t${id}`} className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-dashed border-blue-600 bg-blue-500/15" style={{ left: `${tg.x}%`, top: `${tg.y}%`, width: `${tg.r * 2}%`, aspectRatio: "1" }} />
        ))}
        {labels.map((l, i) => pts[l.id] && (
          <span key={l.id} className={cn("absolute flex h-6 w-6 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-2 border-white text-xs font-bold text-white shadow",
            { "#16a34a": "bg-green-600", "#dc2626": "bg-red-600", "#f97316": "bg-orange-500" }[markColor(result?.reveal?.per_target?.[l.id], result)])}
            style={{ left: `${pts[l.id].x}%`, top: `${pts[l.id].y}%` }}>{i + 1}</span>
        ))}
      </div>
      {!locked && <p className="text-sm text-muted">{t("act.hotspot.tap", { label: labels.find((l) => l.id === active)?.label })}</p>}
    </div>
  );
}

// ── Video with checkpoint questions ───────────────────────────────────

interface YTPlayer { getCurrentTime(): number; pauseVideo(): void; playVideo(): void; seekTo(s: number, allow: boolean): void; destroy(): void }
declare global {
  interface Window { YT?: { Player: new (el: HTMLElement, o: object) => YTPlayer }; onYouTubeIframeAPIReady?: () => void }
}
let ytLoading: Promise<void> | null = null;
function loadYT(): Promise<void> {
  if (window.YT?.Player) return Promise.resolve();
  ytLoading ??= new Promise((resolve, reject) => {
    window.onYouTubeIframeAPIReady = () => resolve();
    const s = document.createElement("script");
    s.src = "https://www.youtube.com/iframe_api";
    s.onerror = () => { ytLoading = null; reject(new Error("yt")); };
    document.head.appendChild(s);
  });
  return ytLoading;
}
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** Minimal player controls shared by the YouTube player and an HTML5 <video> (uploaded lectures). */
interface PlayerCtl { time: () => number; pause: () => void; play: () => void; seek: (t: number) => void }

export function VideoBody({ payload, answer, setAnswer, result, locked }: BodyProps<{ answers?: Record<string, number[]> }>) {
  const { t } = useTranslation();
  const el = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const player = useRef<PlayerCtl | null>(null);
  const cps = payload.checkpoints as { id: string; at: number; question: string; options: string[]; multiple: boolean }[];
  const answers = answer.answers ?? {};
  const [pending, setPending] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const st = useRef({ answers, pending });
  const own = typeof payload.src === "string" && /^\/?api\/media\/lectures\//.test(payload.src) && !payload.video_id;
  useEffect(() => {
    st.current = { answers, pending };
  });

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;
    let yt: YTPlayer | null = null;
    const watch = () => {
      timer = setInterval(() => {
        const p = player.current;
        if (!p || st.current.pending) return;
        const now = p.time();
        if (payload.end && now >= payload.end) p.pause();
        const due = cps.find((c) => now >= c.at && !st.current.answers[c.id]);
        if (due) {
          p.pause();
          setPending(due.id);
        }
      }, 500);
    };
    if (own) {
      const v = video.current;
      if (v) {
        const start = () => { if (v.currentTime < (payload.start || 0)) v.currentTime = payload.start || 0; };
        v.addEventListener("loadedmetadata", start, { once: true });
        player.current = { time: () => v.currentTime, pause: () => v.pause(), play: () => void v.play(), seek: (s) => { v.currentTime = s; } };
        watch();
      }
    } else {
      loadYT().then(() => {
        if (!el.current || !window.YT) return;
        yt = new window.YT.Player(el.current, {
          videoId: payload.video_id, host: "https://www.youtube-nocookie.com",
          playerVars: { start: payload.start || 0, ...(payload.end ? { end: payload.end } : {}), rel: 0, modestbranding: 1, playsinline: 1 },
        });
        player.current = { time: () => yt?.getCurrentTime?.() ?? 0, pause: () => yt?.pauseVideo(), play: () => yt?.playVideo(), seek: (s) => yt?.seekTo(s, true) };
        watch();
      }, () => setFailed(true));
    }
    return () => {
      clearInterval(timer);
      yt?.destroy?.();
      player.current = null;
    };
  }, [own, payload.video_id, payload.src, payload.start, payload.end, cps]);

  const pick = (cid: string, i: number, multiple: boolean) => {
    if (locked) return;
    const cur = answers[cid] ?? [];
    setAnswer({ answers: { ...answers, [cid]: multiple ? (cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i]) : [i] } });
  };
  return (
    <div className="space-y-3">
      <div className="aspect-video w-full overflow-hidden rounded-2xl bg-black">
        {own ? <video ref={video} src={`/${String(payload.src).replace(/^\//, "")}`} controls playsInline preload="metadata" className="h-full w-full" />
          : failed ? <p className="p-6 text-white">{t("act.video.blocked")}</p> : <div ref={el} className="h-full w-full" />}
      </div>
      <ol className="space-y-3">
        {cps.map((c) => {
          const correct = result?.reveal?.correct?.[c.id] as number[] | undefined;
          return (
            <li key={c.id} className={cn("rounded-2xl border-2 p-3", pending === c.id ? "border-accent bg-accent/5" : "border-line")}>
              <p className="mb-2 flex items-center gap-2 text-sm font-semibold">
                <button type="button" className="flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs" onClick={() => player.current?.seek(Math.max(payload.start || 0, c.at - 20))}><Play className="h-3 w-3" />{mmss(c.at)}</button>
                {c.question}
              </p>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {c.options.map((o, i) => (
                  <button key={o} type="button" disabled={locked} aria-pressed={(answers[c.id] ?? []).includes(i)} onClick={() => pick(c.id, i, c.multiple)}
                    className={cn("rounded-xl border-2 px-3 py-1.5 text-left text-sm", (answers[c.id] ?? []).includes(i) ? "border-accent bg-accent/10" : "border-line",
                      correct && (correct.includes(i) ? "border-good bg-good/10" : (answers[c.id] ?? []).includes(i) ? "border-bad bg-bad/10" : ""))}>
                    {o}
                  </button>
                ))}
              </div>
              {pending === c.id && answers[c.id]?.length ? (
                <Button className="mt-2 py-1.5 text-sm" onClick={() => { setPending(null); player.current?.play(); }}>{t("act.video.continue")}</Button>
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// ── Browser task: do it, prove it with a screenshot (graded by the vision model) ──

export function BrowserTaskBody({ payload, answer, setAnswer, locked }: BodyProps<{ image?: string; text?: string }>) {
  const { t } = useTranslation();
  const [err, setErr] = useState("");
  return (
    <div className="space-y-3">
      <ol className="list-decimal space-y-1 pl-5">{(payload.steps as string[]).map((s) => <li key={s}>{s}</li>)}</ol>
      {payload.link && (
        <a href={payload.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent">
          <ExternalLink className="h-4 w-4" /> {new URL(payload.link).hostname}
        </a>
      )}
      <p className="rounded-xl bg-surface-2 px-3 py-2 text-sm"><b>{t("act.browser.proof")}</b> {payload.proof}</p>
      <label className={cn("flex cursor-pointer items-center justify-center gap-2 rounded-2xl border-2 border-dashed p-4 text-sm font-semibold", answer.image ? "border-good" : "border-line hover:border-accent", locked && "pointer-events-none opacity-60")}>
        <Camera className="h-5 w-5" /> {answer.image ? t("act.browser.replace") : t("act.browser.upload")}
        <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" disabled={locked} onChange={async (e) => {
          const f = e.target.files?.[0];
          if (!f) return;
          setErr("");
          try {
            setAnswer({ ...answer, image: await fileToDataUrl(f) });
          } catch {
            setErr(t("act.browser.bad"));
          }
        }} />
      </label>
      {err && <p className="text-sm text-bad">{err}</p>}
      {answer.image && <img src={answer.image} alt={t("act.browser.preview")} className="max-h-64 rounded-xl border border-line" />}
      <textarea value={answer.text ?? ""} disabled={locked} onChange={(e) => setAnswer({ ...answer, text: e.target.value })} rows={2}
        placeholder={t("act.browser.note")} aria-label={t("act.browser.note")} className="w-full rounded-xl border-2 border-line bg-surface p-2 text-sm" />
      <p className="text-xs text-muted">{t("act.browser.privacy")}</p>
      <p className="text-xs text-muted">{t("extension.hint")} <a href="/account" className="font-semibold text-accent underline">{t("extension.hintLink")}</a></p>
    </div>
  );
}

// ── Mini role-play: a short practice conversation inside the card, scored by the coach ─

export function RolePlayBody({ payload, locked, activityId, setAnswer }: BodyProps) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [result, setResult] = useState<RolePlayResult | null>(null);
  const [err, setErr] = useState("");
  async function start() {
    setBusy(true);
    setErr("");
    try {
      const r = await api<{ session_id: number }>(`/api/learn/activities/${activityId}/roleplay/`, { method: "POST" });
      setSession(await roleplay.session(r.session_id));
    } catch {
      setErr(t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-3">
      <div className="rounded-2xl bg-surface-2 p-3 text-sm">
        <p><b>{t("act.rp.you")}</b> {payload.learner_role}</p>
        <p><b>{t("act.rp.talkTo")}</b> {payload.character}</p>
        <p><b>{t("act.rp.where")}</b> {payload.setting}</p>
        <p><b>{t("act.rp.goal")}</b> {payload.goal}</p>
        <ul className="mt-1 space-y-0.5">{(payload.objectives as string[]).map((o) => <li key={o} className="flex gap-1.5"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-accent" />{o}</li>)}</ul>
      </div>
      {result ? (
        <div className="space-y-1 rounded-2xl border-2 border-good/40 bg-good/5 p-3 text-sm">
          <p className="font-display text-2xl font-extrabold">{result.overall}/100</p>
          <p>{result.summary}</p>
          {result.improvements[0] && <p className="text-muted">🎯 {result.improvements[0]}</p>}
          <p className="font-semibold text-accent">{t("act.rp.nowCheck")}</p>
        </div>
      ) : session ? (
        <InlineRolePlay session={session} onFinished={(r) => { setResult(r); setAnswer({ session_id: session.id }); }} />
      ) : !locked && (
        <Button variant="outline" loading={busy} onClick={start}><MessagesSquare className="h-4 w-4" /> {t("act.rp.start")}</Button>
      )}
      {err && <p className="text-sm text-bad">{err}</p>}
    </div>
  );
}
