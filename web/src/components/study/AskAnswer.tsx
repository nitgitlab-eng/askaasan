import { HBars, TimeBars } from "@/components/charts";

export interface AskTable { columns: string[]; rows: (string | number)[][] }

/** The answer to a plain-language data question (learner "Ask your data" and the cockpit's "Ask about my organisation"):
 * a time chart for day/week groupings, bars otherwise, and an optional table (first names only, from the server). */
export type AskAnswerData =
  | { supported: false; note: string }
  | { supported: true; title: string; metric: string; group_by: string; chart: string; data: { label: string; value: number }[]; unit: string; note: string; table?: AskTable | null };

export function AskAnswer({ ans, unsupported, empty, columnLabel = (c) => c }: {
  ans: AskAnswerData;
  /** Shown when the question can't be answered and the model gave no note. */
  unsupported: string;
  empty: string;
  columnLabel?: (column: string) => string;
}) {
  if (!ans.supported) return <p role="status" className="text-sm text-muted">{ans.note || unsupported}</p>;
  const fmt = (v: number) => `${v}${ans.unit}`;
  const tableOnly = ans.chart === "table" && !!ans.table;
  return (
    <div className="space-y-3">
      {!tableOnly && (ans.group_by === "day" || ans.group_by === "week"
        ? <TimeBars title={ans.title} valueLabel={ans.unit || ans.metric} format={fmt} data={ans.data.map((d) => ({ label: d.label.slice(5), value: d.value }))} />
        : <HBars title={ans.title} valueLabel={ans.unit || ans.metric} format={fmt} data={ans.data} empty={empty} />)}
      {ans.table && (ans.table.rows.length || tableOnly) ? (
        <div className="overflow-x-auto">
          {tableOnly && <p className="mb-1 font-display font-bold">{ans.title}</p>}
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr>{ans.table.columns.map((c) => <th key={c} className="border-b border-line px-2 py-1 text-xs font-semibold text-muted">{columnLabel(c)}</th>)}</tr>
            </thead>
            <tbody>
              {ans.table.rows.map((r, i) => (
                <tr key={i} className="border-b border-line/60">{r.map((v, j) => <td key={j} className="px-2 py-1">{String(v)}</td>)}</tr>
              ))}
            </tbody>
          </table>
          {!ans.table.rows.length && <p className="text-sm text-muted">{empty}</p>}
        </div>
      ) : null}
    </div>
  );
}
