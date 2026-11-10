import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SurveyChat } from "@/components/surveys/SurveyChat";
import { Button, Card, Segmented } from "@/components/ui";
import { cn } from "@/lib/cn";
import { orgs, type QType, type Question } from "@/lib/orgs";
import type { Draft } from "@/lib/surveyChat";

const TYPES: QType[] = ["rating", "scale", "nps", "choice", "multi", "text", "matrix"];
const input = "w-full rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm outline-none focus:border-accent";
const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

function blank(type: QType, n: number): Question {
  const q: Question = { id: `q${n}`, type, text: "", required: false };
  if (type === "choice" || type === "multi") q.options = ["", ""];
  if (type === "matrix") Object.assign(q, { rows: ["", ""], options: ["Poor", "OK", "Good"] });
  if (type === "scale") Object.assign(q, { min: 1, max: 10, min_label: "", max_label: "" });
  return q;
}

const SCORABLE: QType[] = ["choice", "multi", "text"];

/** Answer key for a knowledge-test question: the right option(s) or accepted short answers, and points. */
function AnswerKey({ q, upd }: { q: Question; upd: (patch: Partial<Question>) => void }) {
  const { t } = useTranslation();
  const opts = lines((q.options ?? []).join("\n"));
  const multi = Array.isArray(q.correct) ? q.correct : [];
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg bg-good/5 p-2 text-xs">
      {q.type === "choice" && (
        <label className="flex items-center gap-1">{t("credSurvey.q.correct")}
          <select value={typeof q.correct === "string" ? q.correct : ""} onChange={(e) => upd({ correct: e.target.value || undefined })} className="rounded-lg border-2 border-line bg-surface px-1 py-0.5">
            <option value="">{t("credSurvey.q.none")}</option>
            {opts.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </label>
      )}
      {q.type === "multi" && (
        <fieldset className="flex flex-wrap items-center gap-2"><legend className="sr-only">{t("credSurvey.q.correctMulti")}</legend>
          <span>{t("credSurvey.q.correctMulti")}</span>
          {opts.map((o) => (
            <label key={o} className="flex items-center gap-1"><input type="checkbox" checked={multi.includes(o)}
              onChange={(e) => { const next = e.target.checked ? [...multi, o] : multi.filter((x) => x !== o); upd({ correct: next.length ? next : undefined }); }} /> {o}</label>
          ))}
        </fieldset>
      )}
      {q.type === "text" && (
        <label className="block w-full">{t("credSurvey.q.accepted")}
          <textarea rows={2} value={(q.accepted ?? []).join("\n")} onChange={(e) => upd({ accepted: e.target.value ? e.target.value.split("\n") : undefined })} className={input} /></label>
      )}
      <label className="flex items-center gap-1">{t("credSurvey.q.points")}
        <input type="number" min={1} max={100} value={q.points ?? 1} onChange={(e) => upd({ points: Number(e.target.value) || 1 })} className="w-16 rounded-lg border-2 border-line bg-surface px-1 py-0.5" /></label>
    </div>
  );
}

/** Edits a list of questions: add, reorder, required flag, section, options/rows/scale, and (tests) the answer key. */
export function QuestionsEditor({ value, onChange, scored = false }: { value: Question[]; onChange: (q: Question[]) => void; scored?: boolean }) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState<QType>("rating");
  const upd = (i: number, patch: Partial<Question>) => onChange(value.map((q, k) => (k === i ? { ...q, ...patch } : q)));
  const move = (i: number, d: number) => {
    const next = [...value];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    onChange(next);
  };
  const nextId = () => {
    let n = value.length + 1;
    while (value.some((q) => q.id === `q${n}`)) n++;
    return n;
  };
  return (
    <div className="space-y-2">
      {value.map((q, i) => (
        <div key={q.id} className="space-y-2 rounded-xl border-2 border-line p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold">{t(`survey.types.${q.type}`)}</span>
            <input value={q.text} onChange={(e) => upd(i, { text: e.target.value })} maxLength={300} placeholder={t("survey.questionText")} aria-label={t("survey.questionText")} className={cn(input, "min-w-0 flex-1")} />
            <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={!!q.required} onChange={(e) => upd(i, { required: e.target.checked })} /> {t("survey.required")}</label>
            <button disabled={i === 0} onClick={() => move(i, -1)} aria-label={t("lab.up")} className="disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button>
            <button disabled={i === value.length - 1} onClick={() => move(i, 1)} aria-label={t("lab.down")} className="disabled:opacity-30"><ArrowDown className="h-4 w-4" /></button>
            <button onClick={() => onChange(value.filter((_, k) => k !== i))} aria-label={t("lab.delete")}><Trash2 className="h-4 w-4 text-muted" /></button>
          </div>
          <input value={q.section ?? ""} onChange={(e) => upd(i, { section: e.target.value || undefined })} maxLength={80} placeholder={t("credSurvey.q.section")} aria-label={t("credSurvey.q.section")} className={cn(input, "py-1 text-xs")} />
          {(q.type === "choice" || q.type === "multi" || q.type === "matrix") && (
            <label className="block text-xs font-medium">{q.type === "matrix" ? t("survey.columns") : t("survey.options")}
              <textarea rows={3} value={(q.options ?? []).join("\n")} onChange={(e) => upd(i, { options: e.target.value.split("\n") })} className={input} /></label>
          )}
          {q.type === "matrix" && (
            <label className="block text-xs font-medium">{t("survey.rows")}<textarea rows={3} value={(q.rows ?? []).join("\n")} onChange={(e) => upd(i, { rows: e.target.value.split("\n") })} className={input} /></label>
          )}
          {q.type === "scale" && (
            <div className="flex flex-wrap gap-2 text-xs">
              <label className="flex items-center gap-1">{t("survey.from")}<input type="number" min={0} max={9} value={q.min ?? 1} onChange={(e) => upd(i, { min: Number(e.target.value) })} className={cn(input, "w-16")} /></label>
              <input value={q.min_label ?? ""} onChange={(e) => upd(i, { min_label: e.target.value })} maxLength={40} placeholder={t("survey.lowLabel")} className={cn(input, "w-32")} />
              <label className="flex items-center gap-1">{t("survey.to")}<input type="number" min={1} max={10} value={q.max ?? 10} onChange={(e) => upd(i, { max: Number(e.target.value) })} className={cn(input, "w-16")} /></label>
              <input value={q.max_label ?? ""} onChange={(e) => upd(i, { max_label: e.target.value })} maxLength={40} placeholder={t("survey.highLabel")} className={cn(input, "w-32")} />
            </div>
          )}
          {scored && SCORABLE.includes(q.type) && <AnswerKey q={q} upd={(patch) => upd(i, patch)} />}
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-2">
        <select value={adding} onChange={(e) => setAdding(e.target.value as QType)} className="rounded-lg border-2 border-line bg-surface px-2 py-1.5 text-sm" aria-label={t("survey.addType")}>
          {TYPES.map((x) => <option key={x} value={x}>{t(`survey.types.${x}`)}</option>)}
        </select>
        <Button variant="outline" className="py-1.5 text-sm" onClick={() => onChange([...value, blank(adding, nextId())])}><Plus className="h-4 w-4" /> {t("survey.addQuestion")}</Button>
      </div>
    </div>
  );
}

/** Tidy the editor's raw lines before saving; answer keys only survive in test mode and only if they still match. */
function clean(qs: Question[], scored = false): Question[] {
  return qs.map((q) => {
    const options = q.options ? lines(q.options.join("\n")) : undefined;
    const out: Question = { ...q, options, rows: q.rows ? lines(q.rows.join("\n")) : undefined, section: q.section?.trim() || undefined };
    delete out.correct;
    delete out.accepted;
    delete out.points;
    if (!scored) return out;
    if (q.type === "choice" && typeof q.correct === "string" && options?.includes(q.correct)) out.correct = q.correct;
    if (q.type === "multi" && Array.isArray(q.correct)) {
      const c = q.correct.filter((x) => options?.includes(x));
      if (c.length) out.correct = c;
    }
    if (q.type === "text" && q.accepted) {
      const a = lines(q.accepted.join("\n"));
      if (a.length) out.accepted = a;
    }
    if (out.correct !== undefined || out.accepted) out.points = q.points ?? 1;
    return out;
  });
}

type Editing = { id: number; title: string; description: string; questions: Question[]; anonymous: boolean; public?: boolean; draw?: { bank?: number; n?: number };
  kind?: "survey" | "test"; pass_mark?: number; show_review?: boolean; max_attempts?: number; cooldown_minutes?: number };

/** Create or edit a draft survey or knowledge test: write it yourself or with Kili (chat / from a document), add a random
 *  draw from a bank, allow retakes, make it public. */
export function SurveyBuilder({ slug, editing, onSaved, onCancel }: {
  slug: string;
  editing?: Editing;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const { data: banks } = useQuery({ queryKey: ["banks", slug], queryFn: () => orgs.banks(slug) });
  const [title, setTitle] = useState(editing?.title ?? "");
  const [desc, setDesc] = useState(editing?.description ?? "");
  const [qs, setQs] = useState<Question[]>(editing?.questions ?? [blank("rating", 1)]);
  const [anon, setAnon] = useState(editing?.anonymous ?? true);
  const [pub, setPub] = useState(!!editing?.public);
  const [bank, setBank] = useState<number | "">(editing?.draw?.bank ?? "");
  const [n, setN] = useState(editing?.draw?.n ?? 3);
  const [kind, setKind] = useState<"survey" | "test">(editing?.kind ?? "survey");
  const [passMark, setPassMark] = useState(editing?.pass_mark ?? 60);
  const [review, setReview] = useState(editing?.show_review ?? false);
  const [attempts, setAttempts] = useState(editing?.max_attempts ?? 1);
  const [cooldown, setCooldown] = useState(editing?.cooldown_minutes ?? 0);
  const [busy, setBusy] = useState<"" | "save">("");
  const [err, setErr] = useState("");
  const draft: Draft = { title, description: desc, questions: qs };
  const update = (fn: (d: Draft) => Draft) => {
    const next = fn({ title, description: desc, questions: qs });
    setTitle(next.title);
    setDesc(next.description);
    setQs(next.questions);
  };

  async function save() {
    setBusy("save");
    setErr("");
    const body = { title, description: desc, questions: clean(qs, kind === "test"), anonymous: anon, public: pub && kind !== "test", draw: bank ? { bank, n } : {},
      kind, pass_mark: passMark, show_review: review, max_attempts: attempts, cooldown_minutes: cooldown };
    try {
      if (editing) await orgs.setSurvey(slug, editing.id, body);
      else await orgs.createSurvey(slug, body);
      onSaved();
    } catch {
      setErr(t("survey.invalid"));
    } finally {
      setBusy("");
    }
  }
  return (
    <Card className="space-y-3">
      <h3 className="font-display text-lg font-bold">{editing ? t("survey.editDraft") : t("survey.newCustom")}</h3>
      <Segmented label={t("credSurvey.kind.label")} value={kind} onChange={setKind}
        options={[{ value: "survey", label: t("credSurvey.kind.survey") }, { value: "test", label: t("credSurvey.kind.test") }]} />
      <SurveyChat slug={slug} draft={draft} kind={kind} update={update}
        replace={(d) => { setTitle(d.title); setDesc(d.description); setQs(d.questions); }} />
      <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={160} placeholder={t("survey.title")} aria-label={t("survey.title")} className={input} />
      <input value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={500} placeholder={t("survey.description")} aria-label={t("survey.description")} className={input} />
      <QuestionsEditor value={qs} onChange={setQs} scored={kind === "test"} />
      <div className="flex flex-wrap items-center gap-4 rounded-xl bg-surface-2 p-2 text-sm">
        {kind === "test" && (
          <>
            <label className="flex items-center gap-1.5">{t("credSurvey.settings.passMark")}
              <input type="number" min={0} max={100} value={passMark} onChange={(e) => setPassMark(Number(e.target.value))} className="w-16 rounded-lg border-2 border-line bg-surface px-1 py-1" /></label>
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} /> {t("credSurvey.settings.review")}</label>
          </>
        )}
        <label className="flex items-center gap-1.5">{t("credSurvey.settings.attempts")}
          <input type="number" min={0} max={20} value={attempts} onChange={(e) => setAttempts(Number(e.target.value))} className="w-16 rounded-lg border-2 border-line bg-surface px-1 py-1" />
          <span className="text-xs text-muted">{t("credSurvey.settings.unlimited")}</span></label>
        {attempts !== 1 && (
          <label className="flex items-center gap-1.5">{t("credSurvey.settings.cooldown")}
            <input type="number" min={0} max={43200} value={cooldown} onChange={(e) => setCooldown(Number(e.target.value))} className="w-20 rounded-lg border-2 border-line bg-surface px-1 py-1" /></label>
        )}
      </div>
      {kind === "test" && review && attempts !== 1 && <p className="text-xs text-muted">{t("credSurvey.settings.reviewRetakeHint")}</p>}
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <label className="flex items-center gap-1.5"><input type="checkbox" checked={anon} onChange={(e) => setAnon(e.target.checked)} /> {t("org.anonymous")}</label>
        {kind !== "test" && <label className="flex items-center gap-1.5"><input type="checkbox" checked={pub} onChange={(e) => setPub(e.target.checked)} /> {t("survey.public")}</label>}
        {!!banks?.length && (
          <label className="flex items-center gap-1.5">{t("survey.drawFrom")}
            <select value={bank} onChange={(e) => setBank(e.target.value ? Number(e.target.value) : "")} className="rounded-lg border-2 border-line bg-surface px-2 py-1">
              <option value="">{t("survey.noBank")}</option>
              {banks.map((b) => <option key={b.id} value={b.id}>{b.name} ({b.questions.length})</option>)}
            </select>
            {bank !== "" && <input type="number" min={1} max={20} value={n} onChange={(e) => setN(Number(e.target.value))} className="w-14 rounded-lg border-2 border-line bg-surface px-1 py-1" aria-label={t("survey.drawN")} />}
          </label>
        )}
      </div>
      {pub && kind !== "test" && <p className="text-xs text-muted">{t("survey.publicHint")}</p>}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      <div className="flex gap-2">
        <Button loading={busy === "save"} disabled={!title.trim() || !qs.length} onClick={() => void save()}>{t("common.save")}</Button>
        <Button variant="ghost" onClick={onCancel}>{t("lab.cancel")}</Button>
      </div>
    </Card>
  );
}

/** Question banks: reusable pools; surveys can draw N at random per respondent. */
export function BanksManager({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["banks", slug], queryFn: () => orgs.banks(slug) });
  const [edit, setEdit] = useState<{ id?: number; name: string; questions: Question[] } | null>(null);
  const [err, setErr] = useState("");
  return (
    <Card className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-lg font-bold">{t("survey.banks")}</h3>
        {!edit && <Button variant="outline" className="py-1.5 text-sm" onClick={() => setEdit({ name: "", questions: [blank("rating", 1)] })}><Plus className="h-4 w-4" /> {t("survey.newBank")}</Button>}
      </div>
      <p className="text-xs text-muted">{t("survey.banksHint")}</p>
      {data?.map((b) => (
        <div key={b.id} className="flex items-center gap-2 rounded-lg border border-line px-3 py-1.5 text-sm">
          <span className="flex-1">{b.name} · {t("survey.nQuestions", { count: b.questions.length })}</span>
          <button className="text-accent" onClick={() => setEdit(b)}>{t("lab.edit")}</button>
          <button onClick={async () => { await orgs.deleteBank(slug, b.id); void qc.invalidateQueries({ queryKey: ["banks", slug] }); }} aria-label={t("lab.delete")}><Trash2 className="h-4 w-4 text-muted" /></button>
        </div>
      ))}
      {edit && (
        <div className="space-y-2 rounded-xl border-2 border-dashed border-accent/40 p-3">
          <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} placeholder={t("survey.bankName")} className={input} aria-label={t("survey.bankName")} />
          <QuestionsEditor value={edit.questions} onChange={(q) => setEdit({ ...edit, questions: q })} />
          {err && <p className="text-sm text-bad">{err}</p>}
          <div className="flex gap-2">
            <Button onClick={async () => { setErr(""); try { await orgs.saveBank(slug, { ...edit, questions: clean(edit.questions) }); setEdit(null); void qc.invalidateQueries({ queryKey: ["banks", slug] }); } catch { setErr(t("survey.invalid")); } }}>{t("common.save")}</Button>
            <Button variant="ghost" onClick={() => setEdit(null)}>{t("lab.cancel")}</Button>
          </div>
        </div>
      )}
    </Card>
  );
}
