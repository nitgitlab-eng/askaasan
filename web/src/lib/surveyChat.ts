import type { ChatChange, Question } from "./orgs";

export interface Draft { title: string; description: string; questions: Question[] }

/** Apply ONE accepted change from Kili to the builder's draft. Pure: returns a new draft, never mutates.
 *  A change whose target has gone (e.g. the manager already deleted that question) is ignored. */
export function applyChange(d: Draft, c: ChatChange): Draft {
  switch (c.op) {
    case "title":
      return c.text ? { ...d, title: c.text } : d;
    case "description":
      return c.text ? { ...d, description: c.text } : d;
    case "remove":
      return { ...d, questions: d.questions.filter((q) => q.id !== c.target) };
    case "update":
      if (!c.question || !d.questions.some((q) => q.id === c.target)) return d;
      return { ...d, questions: d.questions.map((q) => (q.id === c.target ? { ...c.question!, id: q.id } : q)) };
    case "add": {
      if (!c.question) return d;
      const q = { ...c.question, id: freshId(d.questions, c.question.id) };
      const at = c.after ? d.questions.findIndex((x) => x.id === c.after) : -1;
      const qs = [...d.questions];
      qs.splice(at === -1 ? qs.length : at + 1, 0, q);
      return { ...d, questions: qs };
    }
    default:
      return d;
  }
}

/** Keep the proposed id unless the draft already uses it (the manager may have added questions meanwhile). */
export function freshId(qs: Question[], want: string): string {
  if (!qs.some((q) => q.id === want)) return want;
  let n = qs.length + 1;
  while (qs.some((q) => q.id === `q${n}`)) n++;
  return `q${n}`;
}
