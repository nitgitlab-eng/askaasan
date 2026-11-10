import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Button, Card, Segmented } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { studio, type Preset } from "@/lib/studio";

const input = "w-full rounded-xl border-2 border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent";
const ACT_TYPES = ["quiz", "fill_blank", "sequencing", "categorization", "matching", "open_input", "diagram", "slides", "concept_map", "decision_tree", "task", "viz", "code", "map", "roleplay"];

/** Import a course from a JSON/YAML file or a pasted outline. */
export function ImportCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [format, setFormat] = useState<"outline" | "json" | "yaml">("outline");
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function go(body = text, fmt = format) {
    setBusy(true);
    setErr("");
    try {
      const c = await studio.importCourse(fmt, body, title.trim() || undefined);
      navigate(`/lab/${c.id}`);
    } catch (e) {
      setErr(e instanceof ApiError ? String(e.data?.detail ?? e.data?.code) : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card className="space-y-3">
      <h2 className="flex items-center gap-2 font-display text-xl font-bold"><FileUp className="h-5 w-5 text-accent" /> {t("studio.import.title")}</h2>
      <Segmented label={t("studio.import.format")} value={format} onChange={setFormat}
        options={[{ value: "outline" as const, label: t("studio.import.outline") }, { value: "json" as const, label: "JSON" }, { value: "yaml" as const, label: "YAML" }]} />
      <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} placeholder={t("studio.import.titlePh")} className={input} aria-label={t("studio.import.titlePh")} />
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} placeholder={format === "outline" ? t("studio.import.outlinePh") : t("studio.import.pastePh")}
        className={cn(input, "font-mono text-xs")} aria-label={t("studio.import.title")} />
      <div className="flex flex-wrap items-center gap-2">
        <Button loading={busy} disabled={text.trim().length < 3} onClick={() => void go()}>{t("studio.import.go")}</Button>
        <label className="cursor-pointer text-sm font-semibold text-accent">
          {t("studio.import.file")}
          <input type="file" accept=".json,.yaml,.yml,application/json" className="sr-only" onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            const body = await f.text();
            const fmt = /\.ya?ml$/i.test(f.name) ? "yaml" : "json";
            setFormat(fmt);
            void go(body, fmt);
            e.target.value = "";
          }} />
        </label>
      </div>
      <p className="text-xs text-muted">{t("studio.import.hint")}</p>
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </Card>
  );
}

/** Templates I can start from (org/global/mine), best matches for my skills first. */
export function TemplatesStrip({ forLearner = false }: { forLearner?: boolean }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["templates"], queryFn: () => studio.templates("", true) });
  const [busy, setBusy] = useState<number | null>(null);
  if (!data?.length) return null;
  return (
    <section className="space-y-2">
      <h2 className="font-display text-xl font-bold">{t("studio.templates.title")}</h2>
      <div className="-mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-2">
        {data.map((tpl) => (
          <Card key={tpl.id} className="w-64 shrink-0 snap-start space-y-1">
            <p className="text-2xl" aria-hidden>{tpl.cover_emoji}</p>
            <p className="font-display font-bold leading-tight">{tpl.title}</p>
            <p className="line-clamp-2 text-xs text-muted">{tpl.description}</p>
            <p className="text-xs text-muted">{t(`learn.levels.${tpl.level}`)} · {t("studio.lessonsN", { count: tpl.lessons })}{tpl.org ? ` · ${tpl.org}` : ""}</p>
            {!!tpl.matches.length && <p className="text-xs font-semibold text-accent">{t("studio.templates.matches")}</p>}
            <Button className="mt-1 w-full py-1.5 text-sm" loading={busy === tpl.id} onClick={async () => {
              setBusy(tpl.id);
              try {
                const r = await studio.useTemplate(tpl.id);
                navigate(r.kind === "authored" && !forLearner ? `/lab/${r.id}` : `/learn/${r.id}`);
              } finally {
                setBusy(null);
              }
            }}>{t("studio.templates.use")}</Button>
          </Card>
        ))}
      </div>
    </section>
  );
}

/** Saved pipelines: house style for AI generation (tone, activity mix, lessons per section, instructions). */
export function PresetsManager() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["presets"], queryFn: studio.presets });
  const [edit, setEdit] = useState<Partial<Preset> | null>(null);
  const [err, setErr] = useState("");
  async function save() {
    if (!edit?.name?.trim()) return;
    setErr("");
    try {
      await studio.savePreset(edit);
      setEdit(null);
      void qc.invalidateQueries({ queryKey: ["presets"] });
    } catch {
      setErr(t("mentor.errors.generic"));
    }
  }
  return (
    <Card className="space-y-3" >
      <div id="presets" className="flex items-center justify-between">
        <h2 className="font-display text-xl font-bold">{t("studio.presets.title")}</h2>
        {!edit && <Button variant="outline" onClick={() => setEdit({ name: "", tone: "friendly", activity_types: [], lessons_per_section: 0, instructions: "", level: "", language: "" })}><Plus className="h-4 w-4" /> {t("studio.presets.new")}</Button>}
      </div>
      <p className="text-sm text-muted">{t("studio.presets.sub")}</p>
      {data?.map((p) => (
        <div key={p.id} className="flex items-center gap-2 rounded-xl border border-line px-3 py-2 text-sm">
          <span className="min-w-0 flex-1"><b>{p.name}</b> <span className="text-muted">· {t(`studio.tone.${p.tone}`)}{p.activity_types.length ? ` · ${p.activity_types.length} ${t("studio.presets.types")}` : ""}</span></span>
          <button onClick={() => setEdit(p)} aria-label={t("lab.edit")}><Pencil className="h-4 w-4 text-muted" /></button>
          <button onClick={async () => { await studio.deletePreset(p.id); void qc.invalidateQueries({ queryKey: ["presets"] }); }} aria-label={t("lab.delete")}><Trash2 className="h-4 w-4 text-muted" /></button>
        </div>
      ))}
      {edit && (
        <div className="space-y-2 rounded-2xl border-2 border-dashed border-accent/40 p-3">
          <input value={edit.name ?? ""} onChange={(e) => setEdit({ ...edit, name: e.target.value })} maxLength={80} placeholder={t("studio.presets.name")} className={input} aria-label={t("studio.presets.name")} />
          <div className="flex flex-wrap gap-2">
            <select value={edit.tone} onChange={(e) => setEdit({ ...edit, tone: e.target.value })} className="rounded-xl border-2 border-line bg-surface px-2 py-1.5 text-sm" aria-label={t("studio.presets.tone")}>
              {["friendly", "formal", "playful", "exam"].map((x) => <option key={x} value={x}>{t(`studio.tone.${x}`)}</option>)}
            </select>
            <select value={edit.level} onChange={(e) => setEdit({ ...edit, level: e.target.value })} className="rounded-xl border-2 border-line bg-surface px-2 py-1.5 text-sm" aria-label={t("learn.level")}>
              <option value="">{t("studio.presets.anyLevel")}</option>
              {["beginner", "intermediate", "advanced"].map((x) => <option key={x} value={x}>{t(`learn.levels.${x}`)}</option>)}
            </select>
            <select value={edit.language} onChange={(e) => setEdit({ ...edit, language: e.target.value })} className="rounded-xl border-2 border-line bg-surface px-2 py-1.5 text-sm" aria-label={t("personalize.language")}>
              <option value="">{t("studio.presets.anyLanguage")}</option>
              <option value="en">English</option><option value="ta">தமிழ்</option><option value="tanglish">Tanglish</option>
            </select>
            <label className="flex items-center gap-1 text-sm">{t("studio.presets.perSection")}
              <input type="number" min={0} max={12} value={edit.lessons_per_section ?? 0} onChange={(e) => setEdit({ ...edit, lessons_per_section: Number(e.target.value) })} className="w-16 rounded-xl border-2 border-line bg-surface px-2 py-1" />
            </label>
          </div>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("studio.presets.types")}>
            {ACT_TYPES.map((x) => {
              const on = edit.activity_types?.includes(x);
              return <button key={x} type="button" aria-pressed={on} onClick={() => setEdit({ ...edit, activity_types: on ? edit.activity_types!.filter((y) => y !== x) : [...(edit.activity_types ?? []), x].slice(0, 10) })}
                className={cn("rounded-full border px-2.5 py-0.5 text-xs", on ? "border-accent bg-accent/10 font-semibold" : "border-line")}>{t(`lesson.types.${x}`)}</button>;
            })}
          </div>
          <textarea value={edit.instructions ?? ""} onChange={(e) => setEdit({ ...edit, instructions: e.target.value })} maxLength={800} rows={3} placeholder={t("studio.presets.instructionsPh")} className={input} aria-label={t("studio.presets.instructions")} />
          <div className="flex gap-2"><Button onClick={() => void save()}>{t("common.save")}</Button><Button variant="ghost" onClick={() => setEdit(null)}>{t("lab.cancel")}</Button></div>
          {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        </div>
      )}
    </Card>
  );
}
