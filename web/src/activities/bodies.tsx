import { Reorder } from "motion/react";
import { ArrowDown, ArrowUp, Check, GripVertical, Play, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/cn";

import { Mermaid } from "./Mermaid";
import { runPython } from "./pyodide";
import type { BodyProps, Item } from "./types";

const PALETTE = ["bg-orange-200", "bg-sky-200", "bg-lime-200", "bg-pink-200", "bg-violet-200", "bg-amber-200"];

// ── Quiz / Diagram ────────────────────────────────────────────────────

export function ChoiceBody({ payload, answer, setAnswer, result, locked }: BodyProps<{ selected?: number[] }>) {
  const selected = answer.selected ?? [];
  const correct: number[] | undefined = result?.reveal.correct;
  const toggle = (i: number) => {
    if (locked) return;
    setAnswer({ selected: payload.multiple ? (selected.includes(i) ? selected.filter((x) => x !== i) : [...selected, i]) : [i] });
  };
  return (
    <div className="space-y-3">
      {payload.mermaid && <Mermaid source={payload.mermaid} />}
      <div role={payload.multiple ? "group" : "radiogroup"} className="grid gap-2">
        {(payload.options as string[]).map((opt, i) => {
          const isSel = selected.includes(i);
          const isRight = correct?.includes(i);
          return (
            <button
              key={i}
              role={payload.multiple ? "checkbox" : "radio"}
              aria-checked={isSel}
              onClick={() => toggle(i)}
              disabled={locked}
              className={cn(
                "flex items-center gap-3 rounded-xl border-2 px-4 py-3 text-left transition",
                isSel ? "border-accent bg-accent/10" : "border-line bg-surface hover:border-accent",
                correct && isRight && "border-good bg-good/10",
                correct && isSel && !isRight && "border-bad bg-bad/10",
              )}
            >
              <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 text-sm font-bold", isSel ? "border-accent bg-accent text-accent-ink" : "border-line")}>
                {String.fromCharCode(65 + i)}
              </span>
              <span className="flex-1">{opt}</span>
              {correct && isRight && <Check className="h-5 w-5 text-good" />}
              {correct && isSel && !isRight && <X className="h-5 w-5 text-bad" />}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── Fill in the blanks ────────────────────────────────────────────────

export function FillBlankBody({ payload, answer, setAnswer, result, locked }: BodyProps<{ blanks?: Record<string, string> }>) {
  const blanks = answer.blanks ?? {};
  const per: Record<string, boolean> | undefined = result?.reveal.per_blank;
  const parts = String(payload.text).split(/(\[\[[^\]]+\]\])/g);
  return (
    <p className="text-lg leading-[2.6]">
      {parts.map((part, i) => {
        const m = part.match(/^\[\[([^\]]+)\]\]$/);
        if (!m) return <span key={i}>{part}</span>;
        const id = m[1];
        return (
          <span key={i} className="inline-flex flex-col align-middle">
            <input
              aria-label={`Blank ${id}`}
              value={blanks[id] ?? ""}
              disabled={locked}
              onChange={(e) => setAnswer({ blanks: { ...blanks, [id]: e.target.value } })}
              className={cn(
                "mx-1 w-36 rounded-lg border-b-4 bg-surface-2 px-2 py-0.5 text-center font-semibold outline-none focus:border-accent",
                per ? (per[id] ? "border-good" : "border-bad") : "border-line",
              )}
            />
            {per && !per[id] && <span className="text-center text-xs text-good">{result?.reveal.answers?.[id]}</span>}
          </span>
        );
      })}
    </p>
  );
}

// ── Sequencing (drag to reorder, or arrow buttons) ────────────────────

export function SequencingBody({ payload, answer, setAnswer, result, locked }: BodyProps<{ order?: string[] }>) {
  const { t } = useTranslation();
  const byId = Object.fromEntries((payload.items as Item[]).map((x) => [x.id, x]));
  const order = answer.order ?? (payload.items as Item[]).map((x) => x.id);
  const target: string[] | undefined = result?.reveal.order;
  const move = (idx: number, d: number) => {
    const next = [...order];
    const j = idx + d;
    if (j < 0 || j >= next.length) return;
    [next[idx], next[j]] = [next[j], next[idx]];
    setAnswer({ order: next });
  };
  return (
    <Reorder.Group axis="y" values={order} onReorder={(o) => !locked && setAnswer({ order: o })} className="space-y-2">
      {order.map((id, i) => (
        <Reorder.Item
          key={id}
          value={id}
          dragListener={!locked}
          className={cn(
            "flex cursor-grab items-center gap-3 rounded-xl border-2 bg-surface px-3 py-3 active:cursor-grabbing",
            target ? (target[i] === id ? "border-good bg-good/10" : "border-bad bg-bad/10") : "border-line",
          )}
        >
          <GripVertical className="h-5 w-5 shrink-0 text-muted" />
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-2 text-sm font-bold">{i + 1}</span>
          <span className="flex-1">{byId[id]?.text}</span>
          {!locked && (
            <span className="flex gap-1">
              <button onClick={() => move(i, -1)} aria-label={t("act.moveUp")} className="rounded-lg p-1 hover:bg-surface-2"><ArrowUp className="h-4 w-4" /></button>
              <button onClick={() => move(i, 1)} aria-label={t("act.moveDown")} className="rounded-lg p-1 hover:bg-surface-2"><ArrowDown className="h-4 w-4" /></button>
            </span>
          )}
        </Reorder.Item>
      ))}
    </Reorder.Group>
  );
}

// ── Categorization (tap an item, then tap a bucket) ───────────────────

export function CategorizationBody({ payload, answer, setAnswer, result, locked }: BodyProps<{ assign?: Record<string, string> }>) {
  const { t } = useTranslation();
  const assign = answer.assign ?? {};
  const [picked, setPicked] = useState<string | null>(null);
  const per: Record<string, boolean> | undefined = result?.reveal.per_item;
  const items = payload.items as Item[];
  const place = (cat: string) => {
    if (!picked || locked) return;
    setAnswer({ assign: { ...assign, [picked]: cat } });
    setPicked(null);
  };
  const chip = (it: Item) => (
    <button
      key={it.id}
      disabled={locked}
      onClick={(e) => { e.stopPropagation(); setPicked(picked === it.id ? null : it.id); }}
      aria-pressed={picked === it.id}
      className={cn(
        "rounded-full border-2 px-3 py-1.5 text-sm font-medium transition",
        picked === it.id ? "border-accent bg-accent text-accent-ink" : "border-line bg-surface",
        per && (per[it.id] ? "border-good" : "border-bad"),
      )}
    >
      {it.text}
    </button>
  );
  const unplaced = items.filter((it) => !assign[it.id]);
  return (
    <div className="space-y-3">
      <div className="flex min-h-12 flex-wrap gap-2 rounded-xl border-2 border-dashed border-line p-2">
        {unplaced.length ? unplaced.map(chip) : <span className="text-sm text-muted">✓</span>}
      </div>
      {picked && <p className="text-sm text-muted">{t("lesson.tapBucket")}</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        {(payload.categories as string[]).map((cat, ci) => (
          // A bucket holds placed chips (buttons), so it can't itself be a <button> (nested buttons are invalid HTML
          // and break clicks/screen readers): its name is the button, and tapping anywhere in it still places.
          <div
            key={cat}
            onClick={() => place(cat)}
            className={cn("min-h-24 rounded-2xl border-2 p-3 text-left transition", PALETTE[ci % PALETTE.length], "border-transparent", picked && "ring-2 ring-accent")}
          >
            <button type="button" disabled={locked} onClick={(e) => { e.stopPropagation(); place(cat); }} className="mb-2 block w-full text-left font-display font-bold text-ink">
              {cat}
            </button>
            <div className="flex flex-wrap gap-2">{items.filter((it) => assign[it.id] === cat).map(chip)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Matching (tap left, then right) ───────────────────────────────────

export function MatchingBody({ payload, answer, setAnswer, result, locked }: BodyProps<{ pairs?: Record<string, string> }>) {
  const pairs = answer.pairs ?? {};
  const [left, setLeft] = useState<string | null>(null);
  const per: Record<string, boolean> | undefined = result?.reveal.per_pair;
  const leftIds = (payload.left as Item[]).map((l) => l.id);
  const colorOf = (lid: string) => PALETTE[leftIds.indexOf(lid) % PALETTE.length];
  const rightOwner = (rid: string) => Object.keys(pairs).find((l) => pairs[l] === rid);
  const pickRight = (rid: string) => {
    if (!left || locked) return;
    const next = Object.fromEntries(Object.entries(pairs).filter(([l, r]) => l !== left && r !== rid));
    setAnswer({ pairs: { ...next, [left]: rid } });
    setLeft(null);
  };
  const cell = (key: string, children: ReactNode, cls: string, onClick: () => void, pressed: boolean) => (
    <button key={key} disabled={locked} onClick={onClick} aria-pressed={pressed} className={cn("w-full rounded-xl border-2 px-3 py-3 text-left text-sm font-medium transition", cls)}>
      {children}
    </button>
  );
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="space-y-2">
        {(payload.left as Item[]).map((l) =>
          cell(
            l.id,
            l.text,
            cn(
              pairs[l.id] ? `${colorOf(l.id)} border-transparent text-ink` : "border-line bg-surface",
              left === l.id && "ring-2 ring-accent",
              per && (per[l.id] ? "border-good" : "border-bad"),
            ),
            () => setLeft(left === l.id ? null : l.id),
            left === l.id,
          ),
        )}
      </div>
      <div className="space-y-2">
        {(payload.right as Item[]).map((r) => {
          const owner = rightOwner(r.id);
          return cell(r.id, r.text, cn(owner ? `${colorOf(owner)} border-transparent text-ink` : "border-line bg-surface", left && "hover:border-accent"), () => pickRight(r.id), !!owner);
        })}
      </div>
    </div>
  );
}

// ── Open answer ───────────────────────────────────────────────────────

export function OpenInputBody({ answer, setAnswer, locked }: BodyProps<{ text?: string }>) {
  const { t } = useTranslation();
  return (
    <textarea
      value={answer.text ?? ""}
      disabled={locked}
      onChange={(e) => setAnswer({ text: e.target.value })}
      rows={5}
      placeholder={t("lesson.ownWords")}
      aria-label={t("lesson.ownWords")}
      className="w-full rounded-xl border-2 border-line bg-surface p-3 outline-none focus:border-accent"
    />
  );
}

// ── Code (Python in the browser via Pyodide) ──────────────────────────

export function CodeBody({ payload, answer, setAnswer, result, locked }: BodyProps<{ code?: string; stdout?: string | null }>) {
  const { t } = useTranslation();
  const code = answer.code ?? payload.starter_code ?? "";
  const [running, setRunning] = useState(false);
  const [out, setOut] = useState<{ stdout: string; error?: string } | null>(null);
  async function run() {
    setRunning(true);
    try {
      const r = await runPython(code);
      setOut(r);
      setAnswer({ code, stdout: r.stdout });
    } finally {
      setRunning(false);
    }
  }
  return (
    <div className="space-y-2">
      <textarea
        value={code}
        disabled={locked}
        spellCheck={false}
        onChange={(e) => setAnswer({ code: e.target.value, stdout: null })}
        onKeyDown={(e) => {
          if (e.key === "Tab") {
            e.preventDefault();
            const el = e.currentTarget;
            const s = el.selectionStart;
            const v = code.slice(0, s) + "    " + code.slice(el.selectionEnd);
            setAnswer({ code: v, stdout: null });
            requestAnimationFrame(() => el.setSelectionRange(s + 4, s + 4));
          }
        }}
        rows={Math.max(6, code.split("\n").length + 1)}
        aria-label={t("act.code.editor")}
        className="w-full rounded-xl border-2 border-line bg-[#1e1b16] p-3 font-mono text-sm text-[#f5ece3] outline-none focus:border-accent"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={run} disabled={running} className="flex items-center gap-2 rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent">
          <Play className="h-4 w-4" /> {running ? t("lesson.running") : t("lesson.run")}
        </button>
        <span className="text-xs text-muted">{t("lesson.expected")}: <code>{payload.expected_output}</code></span>
      </div>
      {out && (
        <pre className={cn("overflow-x-auto rounded-xl p-3 font-mono text-sm", out.error ? "bg-bad/10 text-bad" : "bg-surface-2")}>{out.error ?? (out.stdout || t("act.code.noOutput"))}</pre>
      )}
      {result?.reveal.model_solution && (
        <details className="rounded-xl bg-surface-2 p-3 text-sm">
          <summary className="cursor-pointer font-semibold">{t("lesson.showSolution")}</summary>
          <pre className="mt-2 overflow-x-auto font-mono">{result.reveal.model_solution}</pre>
        </details>
      )}
    </div>
  );
}
