import { api } from "./api";

export interface ArticleRow { slug: string; category: string; title: string; title_ta: string }
export interface Article extends ArticleRow { body_md: string; body_ta_md: string; updated_at: string }
export interface Report { id: number; category: string; text: string; page: string; status: "new" | "triaging" | "fixed" | "closed"; reply: string; replied_at: string | null; created_at: string; screenshot: string }

export const support = {
  articles: (q = "") => api<ArticleRow[]>(`/api/support/articles/${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  article: (slug: string) => api<Article>(`/api/support/articles/${slug}/`),
  ask: (question: string) => api<{ answer: string; sources: ArticleRow[]; found: boolean }>("/api/support/ask/", { method: "POST", json: { question } }),
  reports: () => api<Report[]>("/api/support/reports/"),
  report: (body: { category: string; text: string; page?: string; ref?: string; screenshot?: string; browser?: string }) =>
    api<Report>("/api/support/reports/", { method: "POST", json: body }),
};
