import { BookOpen, Check, FileText, MessagesSquare, StickyNote, Users } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { cn } from "@/lib/cn";
import { shortDate, type ItemKind, type LearnerItem } from "@/lib/journeys";
import { roleplay } from "@/lib/roleplay";

const KIND_ICON: Record<ItemKind, typeof BookOpen> = { lesson: BookOpen, scenario: MessagesSquare, shadow: Users, document: FileText, note: StickyNote };

/** One journey item for the learner: what to do, when, and a tick (lesson items tick themselves when the lesson is done). */
export function JourneyItemRow({ item, onTick, busy }: { item: LearnerItem; onTick?: (done: boolean) => void; busy?: boolean }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [starting, setStarting] = useState(false);
  const Icon = KIND_ICON[item.kind];
  const who = [item.colleague_name, item.colleague_role].filter(Boolean).join(" · ");
  const sub = item.kind === "lesson" ? (item.lesson ? item.course?.title : "") : item.kind === "shadow" ? who : "";

  async function practise() {
    if (!item.scenario) return;
    setStarting(true);
    try {
      const s = await roleplay.start(item.scenario.id);
      navigate(`/roleplay/${s.id}`);
    } finally {
      setStarting(false);
    }
  }

  return (
    <li className={cn("flex items-start gap-3 rounded-xl border border-line p-3", item.done && "opacity-70", item.overdue && "border-bad/50")}>
      <span className={cn("mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl", item.done ? "bg-good text-white" : "bg-surface-2 text-accent")}>
        {item.done ? <Check className="h-5 w-5" aria-label={t("jr.done")} /> : <Icon className="h-5 w-5" aria-hidden />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t(`jr.kinds.${item.kind}`)} · {t("jr.dayN", { n: item.day })} · {shortDate(item.due_date, i18n.language)}</p>
        <p className={cn("font-semibold", item.done && "line-through")}>{item.unavailable ? <span className="italic text-muted">{t("jr2.docUnavailable")}</span> : item.title}</p>
        {sub && <p className="text-sm text-muted">{sub}</p>}
        {item.notes && <p className="mt-1 whitespace-pre-line text-sm">{item.notes}</p>}
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          {item.overdue && <span className="rounded-full bg-bad px-2 py-0.5 text-xs font-bold text-white">{t("jr.overdue")}</span>}
          {item.link && (
            <Link to={item.link} className="rounded-lg border-2 border-accent px-2.5 py-1 font-semibold text-accent hover:bg-accent hover:text-accent-ink">
              {item.kind === "document" ? t("jr.readDoc") : t("jr.open")}
            </Link>
          )}
          {item.kind === "scenario" && item.scenario && (
            <button disabled={starting} onClick={() => void practise()} className="rounded-lg border-2 border-accent px-2.5 py-1 font-semibold text-accent hover:bg-accent hover:text-accent-ink disabled:opacity-60">
              {item.scenario.emoji} {t("jr.startPractice")}
            </button>
          )}
          {item.unavailable ? null : item.auto ? (
            <span className="text-xs text-muted">{t("jr.autoDone")}</span>
          ) : onTick && (
            <label className="flex cursor-pointer items-center gap-1.5 text-sm font-medium">
              <input type="checkbox" checked={item.done} disabled={busy} onChange={(e) => onTick(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
              {t("jr.markDone")}
            </label>
          )}
        </div>
      </div>
    </li>
  );
}
