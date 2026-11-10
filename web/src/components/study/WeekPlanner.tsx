import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight, MoreHorizontal, Plus, SkipForward, Trash2, Undo2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { localeOf } from "@/i18n/languages";
import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { addDays, isoDay, study, type Block, type Week } from "@/lib/study";

import { CalendarConnect } from "./CalendarConnect";

const input = "rounded-lg border-2 border-line bg-surface px-2 py-1 text-sm";

/** P4: the week as study blocks — drag (or use ⋯) to reschedule, skip re-plans onto the next free day. */
export function WeekPlanner() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [week, setWeek] = useState<string | undefined>(undefined);
  const { data } = useQuery({ queryKey: ["blocks", week ?? "now"], queryFn: () => study.week(week) });
  const [drag, setDrag] = useState<number | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [note, setNote] = useState("");
  const [today] = useState(() => isoDay(new Date()));
  const locale = localeOf(i18n.language);
  const fmt = (iso: string, o: Intl.DateTimeFormatOptions) => new Date(`${iso}T00:00:00`).toLocaleDateString(locale, o);

  const apply = (w: Week) => {
    qc.setQueryData(["blocks", week ?? "now"], w);
    void qc.invalidateQueries({ queryKey: ["blocks"], refetchType: "none" });
    void qc.invalidateQueries({ queryKey: ["plan"] });
  };
  async function act(b: Block, action: "skip" | "done" | "undo" | "move" | "delete", extra: { date?: string; start?: string } = {}) {
    setNote("");
    try {
      const w = await study.blockAction(b.id, action, extra);
      apply(w);
      if (action === "skip") setNote(w.moved_to ? t("planner.movedTo", { day: fmt(w.moved_to, { weekday: "long", day: "numeric", month: "short" }) }) : t("planner.skipped"));
      setOpen(null);
    } catch (e) {
      setNote(e instanceof ApiError && e.data?.code === "out_of_range" ? t("planner.outOfRange") : t("mentor.errors.generic"));
    }
  }
  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      apply(await study.addBlock({ date: String(f.get("date")), start: String(f.get("start")), minutes: Number(f.get("minutes")), title: String(f.get("title")).trim() }));
      setAdding(false);
    } catch {
      setNote(t("planner.addFailed"));
    }
  }
  if (!data) return <Card><p className="text-muted">{t("common.loading")}</p></Card>;
  const title = (b: Block) => b.title || t(`planner.kind.${b.kind}`, { defaultValue: t("planner.kind.lesson") });

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-xl font-bold">{t("planner.title")}</h2>
        <div className="flex items-center gap-1">
          <button aria-label={t("planner.prev")} onClick={() => setWeek(addDays(data.start, -7))} className="rounded-lg p-1.5 hover:bg-surface-2"><ChevronLeft className="h-4 w-4" /></button>
          <span className="text-sm font-medium">{fmt(data.start, { day: "numeric", month: "short" })} – {fmt(addDays(data.start, 6), { day: "numeric", month: "short" })}</span>
          <button aria-label={t("planner.next")} onClick={() => setWeek(addDays(data.start, 7))} className="rounded-lg p-1.5 hover:bg-surface-2"><ChevronRight className="h-4 w-4" /></button>
        </div>
      </div>
      {note && <p role="status" className="rounded-xl bg-accent/10 px-3 py-2 text-sm">{note}</p>}
      <div className="grid gap-2 md:grid-cols-7">
        {data.days.map((d) => {
          const blocks = data.blocks.filter((b) => b.date === d.day);
          const past = d.day < today;
          return (
            <section key={d.day} aria-label={fmt(d.day, { weekday: "long", day: "numeric" })}
              onDragOver={(e) => { if (!past) e.preventDefault(); }}
              onDrop={() => { const b = data.blocks.find((x) => x.id === drag); if (b && b.date !== d.day) void act(b, "move", { date: d.day }); setDrag(null); }}
              className={cn("min-h-24 rounded-2xl border-2 p-2", d.day === today ? "border-accent" : "border-line", d.paused && "bg-surface-2/70", past && "opacity-70")}>
              <p className="mb-1 flex items-center justify-between text-xs font-semibold">
                <span>{fmt(d.day, { weekday: "short", day: "numeric" })}</span>
                {d.studied && <Check className="h-3.5 w-3.5 text-good" aria-label={t("planner.studied")} />}
              </p>
              {d.paused && <p className="text-[11px] text-muted">⏸ {t("planner.paused")}</p>}
              <ul className="space-y-1.5">
                {blocks.map((b) => (
                  <li key={b.id} draggable={b.status !== "skipped" && !past} onDragStart={() => setDrag(b.id)}
                    className={cn("rounded-xl border px-2 py-1.5 text-xs",
                      b.state === "done" ? "border-good/50 bg-good/10" : b.state === "missed" ? "border-bad/40 bg-bad/5" : b.state === "skipped" ? "border-line line-through opacity-50" : "border-accent/40 bg-surface")}>
                    <div className="flex items-start gap-1">
                      <div className="min-w-0 flex-1">
                        <p className="tabular-nums text-muted">{b.start} · {b.minutes}m{b.moved_from && " ↪"}</p>
                        {b.link ? <Link to={b.link} className="line-clamp-2 font-semibold hover:text-accent">{title(b)}</Link> : <p className="line-clamp-2 font-semibold">{title(b)}</p>}
                      </div>
                      <button onClick={() => setOpen(open === b.id ? null : b.id)} aria-label={t("planner.actions")} aria-expanded={open === b.id} className="rounded p-0.5 hover:bg-surface-2"><MoreHorizontal className="h-3.5 w-3.5" /></button>
                    </div>
                    {open === b.id && (
                      <div className="mt-1.5 space-y-1.5 border-t border-line pt-1.5">
                        <div className="flex flex-wrap gap-1">
                          {b.status === "planned" && <button onClick={() => void act(b, "done")} className="flex items-center gap-0.5 rounded bg-good/15 px-1.5 py-0.5"><Check className="h-3 w-3" />{t("planner.done")}</button>}
                          {b.status === "planned" && <button onClick={() => void act(b, "skip")} className="flex items-center gap-0.5 rounded bg-surface-2 px-1.5 py-0.5"><SkipForward className="h-3 w-3" />{t("planner.skip")}</button>}
                          {b.status !== "planned" && <button onClick={() => void act(b, "undo")} className="flex items-center gap-0.5 rounded bg-surface-2 px-1.5 py-0.5"><Undo2 className="h-3 w-3" />{t("planner.undo")}</button>}
                          {!b.auto && <button onClick={() => void act(b, "delete")} aria-label={t("planner.delete")} className="rounded bg-bad/10 px-1.5 py-0.5 text-bad"><Trash2 className="h-3 w-3" /></button>}
                        </div>
                        <form className="flex flex-wrap items-center gap-1" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); void act(b, "move", { date: String(f.get("date")), start: String(f.get("start")) }); }}>
                          <input name="date" type="date" defaultValue={b.date} min={addDays(today, -1)} aria-label={t("planner.date")} className={cn(input, "w-full px-1 text-xs")} />
                          <input name="start" type="time" defaultValue={b.start} aria-label={t("planner.time")} className={cn(input, "px-1 text-xs")} />
                          <button className="rounded bg-accent px-1.5 py-0.5 font-semibold text-accent-ink">{t("planner.move")}</button>
                        </form>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
      <p className="text-xs text-muted">{t("planner.hint")}</p>
      <CalendarConnect />
      {adding ? (
        <form onSubmit={(e) => void add(e)} className="flex flex-wrap items-end gap-2 rounded-2xl border-2 border-dashed border-line p-3">
          <label className="flex flex-col text-xs font-medium">{t("planner.blockTitle")}<input name="title" required maxLength={200} className={input} placeholder={t("planner.titlePh")} /></label>
          <label className="flex flex-col text-xs font-medium">{t("planner.date")}<input name="date" type="date" required defaultValue={today} min={today} className={input} /></label>
          <label className="flex flex-col text-xs font-medium">{t("planner.time")}<input name="start" type="time" required defaultValue="19:00" className={input} /></label>
          <label className="flex flex-col text-xs font-medium">{t("planner.minutes")}<input name="minutes" type="number" min={5} max={240} defaultValue={20} className={cn(input, "w-20")} /></label>
          <Button type="submit">{t("common.save")}</Button>
          <Button type="button" variant="ghost" onClick={() => setAdding(false)}>{t("common.close")}</Button>
        </form>
      ) : (
        <Button variant="outline" onClick={() => setAdding(true)}><Plus className="h-4 w-4" /> {t("planner.add")}</Button>
      )}
    </Card>
  );
}
