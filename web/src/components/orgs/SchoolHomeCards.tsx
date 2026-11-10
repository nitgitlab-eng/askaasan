/** Home cards for org members: a gentle prompt to fill self-fill member fields, and partner-cohort courses with their access window. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, UserPen } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { ApiError } from "@/lib/api";
import { school, type MyOrgFields } from "@/lib/school";

const DISMISS = "aasan:fields-prompt-dismissed";

function dismissedToday(): boolean {
  try {
    return localStorage.getItem(DISMISS) === new Date().toDateString();
  } catch {
    return false;
  }
}

export function MemberFieldsPrompt() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["my-fields"], queryFn: school.myFields });
  const [open, setOpen] = useState(false);
  const [hidden, setHidden] = useState(dismissedToday);
  if (!data?.missing || hidden) return null;
  const orgsWithMissing = data.orgs.filter((o) => o.fields.some((f) => f.missing));
  return (
    <Card className="space-y-3 border-2 border-accent/30 bg-accent/5">
      <div className="flex items-start gap-3">
        <UserPen className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{t("school.fields.promptTitle", { org: orgsWithMissing[0]?.org ?? "" })}</p>
          <p className="text-sm text-muted">{t("school.fields.promptSub", { count: data.missing })}</p>
        </div>
        {!open && <Button className="py-1.5 text-sm" onClick={() => setOpen(true)}>{t("school.fields.fill")}</Button>}
      </div>
      {open && orgsWithMissing.map((o) => <FieldsForm key={o.slug} o={o} onDone={() => setOpen(false)} />)}
      {!open && (
        <button className="text-xs text-muted hover:text-accent" onClick={() => {
          try { localStorage.setItem(DISMISS, new Date().toDateString()); } catch { /* private mode */ }
          setHidden(true);
        }}>{t("school.fields.later")}</button>
      )}
    </Card>
  );
}

function FieldsForm({ o, onDone }: { o: MyOrgFields; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const editable = o.fields.filter((f) => f.editable);
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(editable.map((f) => [f.key, f.value])));
  const [err, setErr] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr("");
    try {
      await school.saveMyFields(o.slug, vals);
      await qc.invalidateQueries({ queryKey: ["my-fields"] });
      onDone();
    } catch (x) {
      setErr(x instanceof ApiError && x.data?.code === "bad_option" ? t("school.fields.badOption") : t("mentor.errors.generic"));
    }
  };
  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-2">
      {o.fields.filter((f) => !f.editable && f.value).map((f) => (
        <p key={f.key} className="text-sm"><span className="text-muted">{f.label}:</span> {f.value}</p>
      ))}
      {editable.map((f) => (
        <label key={f.key} className="block text-sm">
          {f.label}{f.missing && <span className="text-accent"> *</span>}
          {f.type === "select" ? (
            <select value={vals[f.key] ?? ""} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} className="mt-1 w-full rounded-lg border-2 border-line bg-surface px-2 py-1.5">
              <option value="">—</option>
              {f.options.map((x) => <option key={x} value={x}>{x}</option>)}
            </select>
          ) : (
            <input value={vals[f.key] ?? ""} maxLength={80} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} className="mt-1 w-full rounded-lg border-2 border-line bg-surface px-2 py-1.5" />
          )}
        </label>
      ))}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
      <Button type="submit" className="py-1.5 text-sm">{t("common.save")}</Button>
    </form>
  );
}

export function CohortCourses() {
  const { t, i18n } = useTranslation();
  const { data } = useQuery({ queryKey: ["my-cohorts"], queryFn: school.myCohorts });
  if (!data?.length) return null;
  const fmt = (d: string) => new Date(d).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short", year: "numeric" });
  return (
    <Card>
      <h2 className="mb-3 font-display text-xl font-bold">{t("school.myCohorts.title")}</h2>
      <ul className="space-y-3">
        {data.map((c) => (
          <li key={c.id}>
            <p className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-semibold">{c.name}</span>
              <span className="text-muted">{c.partner || c.org}</span>
              <span className="ml-auto flex items-center gap-1 text-xs text-muted"><CalendarClock className="h-3.5 w-3.5" />
                {c.state === "upcoming" ? t("school.myCohorts.startsOn", { d: fmt(c.starts_at) }) : c.state === "active" ? t("school.myCohorts.until", { d: fmt(c.ends_at) }) : t("school.myCohorts.ended", { d: fmt(c.ends_at) })}
              </span>
            </p>
            <ul className="divide-y divide-line">
              {c.courses.map((x) => (
                <li key={x.id}>
                  {c.state === "active" ? (
                    <Link to={`/learn/${x.id}`} className="flex items-center gap-3 py-2 hover:text-accent"><span className="text-2xl">{x.emoji}</span><span className="truncate font-medium">{x.title}</span></Link>
                  ) : (
                    <p className="flex items-center gap-3 py-2 text-muted"><span className="text-2xl opacity-60">{x.emoji}</span><span className="truncate">{x.title}</span></p>
                  )}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </Card>
  );
}
