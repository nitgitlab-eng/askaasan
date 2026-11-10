import { Code2, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { lab, type LabActivity } from "@/lib/lab";

import { ArtifactCheckForm } from "./ArtifactCheckForm";
import { HotspotForm, VideoForm } from "./CreatorForms";
import { ImageField } from "./MediaPicker";
import { ObserveStepsEditor } from "./ObserveStepsEditor";

const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
const input = "w-full rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent";

/**
 * Friendly forms for the common types; a validated JSON editor for the rest.
 * The server re-validates every save with the same rules as AI output.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function ActivityEditor({ a, lessonId, onSaved, onDeleted }: { a: LabActivity; lessonId: number; onSaved: (x: LabActivity) => void; onDeleted: () => void }) {
  const { t } = useTranslation();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [src, setSrc] = useState<Record<string, any>>(a.source ?? {});
  const [json, setJson] = useState(JSON.stringify(a.source ?? {}, null, 2));
  const [advanced, setAdvanced] = useState(!["quiz", "fill_blank", "sequencing", "matching", "categorization", "open_input", "video", "hotspot", "artifact_check"].includes(a.type));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const set = (k: string, v: any) => setSrc({ ...src, [k]: v });

  async function save() {
    setBusy(true);
    setError("");
    try {
      const source = advanced ? JSON.parse(json) : src;
      onSaved(await lab.saveActivity(a.id, source));
    } catch (e) {
      setError(e instanceof SyntaxError ? t("lab.badJson") : e instanceof ApiError ? String(e.data?.detail ?? e.data?.code) : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }

  if (!a.editable) return <p className="text-sm text-muted">{t("lab.notEditable")}</p>;
  return (
    <div className="space-y-3 rounded-2xl border-2 border-dashed border-accent/40 bg-surface-2/50 p-4">
      {a.type !== "hotspot" && (
        <div className="space-y-1 text-sm font-medium">
          <p>{t("lab.media.activityImage")}</p>
          <ImageField value={advanced ? (() => { try { return JSON.parse(json).image; } catch { return ""; } })() : src.image}
            suggestion={src.prompt ?? ""}
            onChange={(u) => {
              set("image", u);
              try { setJson(JSON.stringify({ ...JSON.parse(json), image: u }, null, 2)); } catch { /* invalid JSON: form value still updates */ }
            }} />
        </div>
      )}
      {!advanced && (
        <>
          <label className="block space-y-1 text-sm font-medium">{t("lab.f.title")}<input className={input} value={src.title ?? ""} onChange={(e) => set("title", e.target.value)} /></label>
          <label className="block space-y-1 text-sm font-medium">{t("lab.f.prompt")}<input className={input} value={src.prompt ?? ""} onChange={(e) => set("prompt", e.target.value)} /></label>
          {a.type === "video" && <VideoForm src={src} setSrc={setSrc} lessonId={lessonId} />}
          {a.type === "hotspot" && <HotspotForm src={src} setSrc={setSrc} />}
          {a.type === "artifact_check" && <ArtifactCheckForm src={src} setSrc={setSrc} />}
          {a.type === "quiz" && (
            <div className="space-y-2">
              <p className="text-sm font-medium">{t("lab.f.options")}</p>
              {(src.options as string[]).map((o, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input type="checkbox" checked={src.correct.includes(i)} aria-label={t("lab.f.correct")}
                    onChange={(e) => set("correct", e.target.checked ? [...src.correct, i].sort() : src.correct.filter((x: number) => x !== i))} />
                  <input className={input} value={o} onChange={(e) => set("options", src.options.map((x: string, k: number) => (k === i ? e.target.value : x)))} />
                  <button onClick={() => setSrc({ ...src, options: src.options.filter((_: string, k: number) => k !== i), correct: src.correct.filter((x: number) => x !== i).map((x: number) => (x > i ? x - 1 : x)) })} aria-label={t("lab.remove")}><Trash2 className="h-4 w-4 text-muted" /></button>
                </div>
              ))}
              <button className="text-sm font-semibold text-accent" onClick={() => set("options", [...src.options, ""])}>+ {t("lab.f.addOption")}</button>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!src.multiple} onChange={(e) => set("multiple", e.target.checked)} /> {t("lab.f.multiple")}</label>
            </div>
          )}
          {a.type === "fill_blank" && (
            <>
              <label className="block space-y-1 text-sm font-medium">{t("lab.f.blankText")}<textarea className={input} rows={2} value={src.text} onChange={(e) => set("text", e.target.value)} /></label>
              {(src.blanks as { id: string; answers: string[] }[]).map((b, i) => (
                <label key={b.id} className="block space-y-1 text-sm font-medium">[[{b.id}]] {t("lab.f.answers")}
                  <input className={input} value={b.answers.join(", ")} onChange={(e) => set("blanks", src.blanks.map((x: object, k: number) => (k === i ? { ...b, answers: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) } : x)))} />
                </label>
              ))}
            </>
          )}
          {a.type === "sequencing" && (
            <label className="block space-y-1 text-sm font-medium">{t("lab.f.steps")}<textarea className={input} rows={5} value={(src.items_in_order ?? []).join("\n")} onChange={(e) => set("items_in_order", lines(e.target.value))} /></label>
          )}
          {a.type === "matching" && (
            <label className="block space-y-1 text-sm font-medium">{t("lab.f.pairs")}
              <textarea className={input} rows={5} value={(src.pairs ?? []).map((p: { left: string; right: string }) => `${p.left} => ${p.right}`).join("\n")}
                onChange={(e) => set("pairs", lines(e.target.value).map((l) => { const [left, right = ""] = l.split("=>"); return { left: left.trim(), right: right.trim() }; }))} />
            </label>
          )}
          {a.type === "categorization" && (
            <>
              <label className="block space-y-1 text-sm font-medium">{t("lab.f.categories")}<input className={input} value={(src.categories ?? []).join(", ")} onChange={(e) => set("categories", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} /></label>
              <label className="block space-y-1 text-sm font-medium">{t("lab.f.items")}
                <textarea className={input} rows={5} value={(src.items ?? []).map((p: { text: string; category: string }) => `${p.text} => ${p.category}`).join("\n")}
                  onChange={(e) => set("items", lines(e.target.value).map((l) => { const [text, category = ""] = l.split("=>"); return { text: text.trim(), category: category.trim() }; }))} />
              </label>
            </>
          )}
          {a.type === "open_input" && (
            <>
              <label className="block space-y-1 text-sm font-medium">{t("lab.f.modelAnswer")}<textarea className={input} rows={3} value={src.model_answer} onChange={(e) => set("model_answer", e.target.value)} /></label>
              <label className="block space-y-1 text-sm font-medium">{t("lab.f.rubric")}<textarea className={input} rows={3} value={(src.rubric ?? []).join("\n")} onChange={(e) => set("rubric", lines(e.target.value))} /></label>
            </>
          )}
          {"explanation" in src && (
            <label className="block space-y-1 text-sm font-medium">{t("lab.f.explanation")}<input className={input} value={src.explanation} onChange={(e) => set("explanation", e.target.value)} /></label>
          )}
        </>
      )}
      {advanced && (
        <textarea value={json} onChange={(e) => setJson(e.target.value)} rows={14} spellCheck={false} aria-label="JSON"
          className="w-full rounded-xl border-2 border-line bg-[#1e1b16] p-3 font-mono text-xs text-[#f5ece3] outline-none focus:border-accent" />
      )}
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      {a.type === "browser_task" && <ObserveStepsEditor activityId={a.id} />}
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={save} loading={busy}>{t("common.save")}</Button>
        <Button variant="ghost" onClick={() => { setJson(JSON.stringify(src, null, 2)); setAdvanced(!advanced); }}><Code2 className="h-4 w-4" /> {advanced ? t("lab.formMode") : t("lab.jsonMode")}</Button>
        <Button variant="ghost" className="ml-auto text-bad" onClick={async () => { await lab.deleteActivity(a.id); onDeleted(); }}><Trash2 className="h-4 w-4" /> {t("lab.delete")}</Button>
      </div>
    </div>
  );
}
