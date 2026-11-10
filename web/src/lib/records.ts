import { api } from "./api";

/** One compliance training record (append-only on the server). `score` is a whole percent. */
export interface TrainingRecord {
  id: number;
  learner: string;
  email: string;
  kind: "course" | "scenario" | "workshop" | "test";
  title: string;
  assigned_at: string | null;
  started_at: string | null;
  completed_at: string;
  score: number | null;
  minutes: number | null;
  certificate_code: string;
  verify_url: string;
  org: string;
  backfilled: boolean;
}

export type RecordFormat = "csv" | "xlsx" | "pdf";

export const records = {
  mine: () => api<TrainingRecord[]>("/api/orgs/me/training-record/"),
  urls: {
    org: (slug: string, fmt: RecordFormat) =>
      fmt === "csv" ? `/api/orgs/${slug}/training-records/?export=csv` : `/api/orgs/${slug}/training-records.${fmt}`,
    mine: (fmt: Exclude<RecordFormat, "csv">) => `/api/orgs/me/training-record.${fmt}`,
  },
};
