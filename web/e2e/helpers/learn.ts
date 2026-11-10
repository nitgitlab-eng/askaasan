import type { Api } from "./api";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export interface Course {
  id: number;
  title: string;
  sections: { id: number; title: string; subsections: { id: number; title: string; locked: boolean; state: string }[] }[];
}

/** Builds a personal course through the real API (fake AI) and waits until it's ready. */
export async function createCourse(api: Api, goal = "Understand how AI chatbots work"): Promise<Course> {
  const c = await api.post("/api/learn/curriculums/", { goal, level: "beginner", domain: "ai" });
  for (let i = 0; i < 60; i++) {
    const d = await api.get(`/api/learn/curriculums/${c.id}/`);
    if (d.status === "ready") return d;
    if (d.status === "failed") throw new Error(`course ${c.id} failed: ${d.error}`);
    await sleep(1000);
  }
  throw new Error(`course ${c.id} still generating`);
}

/** Correct answers for the fake provider's standard lesson (see api/llm/providers/fake_provider.py). */
const ANSWERS: Record<string, (p: any) => unknown> = {
  quiz: () => ({ selected: [1] }),
  fill_blank: () => ({ blanks: { "1": "data" } }),
  sequencing: (p) => ({ order: ["Collect data", "Train model", "Make predictions"].map((t) => p.items.find((i: any) => i.text === t).id) }),
  categorization: (p) => ({ assign: Object.fromEntries(p.items.map((i: any) => [i.id, i.text === "Spam filter" ? "AI" : "Not AI"])) }),
  matching: (p) => {
    const right = (t: string) => p.right.find((r: any) => r.text === t).id;
    return { pairs: Object.fromEntries(p.left.map((l: any) => [l.id, right(l.text === "Data" ? "Examples" : "Learned pattern")])) };
  },
};

/** Opens, answers and completes a lesson through the API (setup for review/certificate specs). */
export async function completeLessonViaApi(api: Api, lessonId: number) {
  let l = await api.post(`/api/learn/subsections/${lessonId}/start/`);
  for (let i = 0; i < 60 && l.lesson_status !== "ready"; i++) {
    await sleep(1000);
    l = await api.get(`/api/learn/subsections/${lessonId}/`);
  }
  for (const a of l.activities) {
    const answer = ANSWERS[a.type]?.(a.payload);
    if (answer) await api.post(`/api/learn/activities/${a.id}/attempt/`, { answer });
  }
  return api.post(`/api/learn/subsections/${lessonId}/complete/`);
}
