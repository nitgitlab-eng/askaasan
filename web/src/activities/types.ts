export type ActivityType =
  | "quiz" | "fill_blank" | "sequencing" | "categorization" | "matching" | "open_input" | "code" | "diagram"
  | "slides" | "concept_map" | "viz" | "decision_tree" | "task"
  | "map" | "browser_task" | "roleplay" | "video" | "hotspot" | "artifact_check";

export interface Item {
  id: string;
  text: string;
}

export interface ActivityData {
  id: number;
  type: ActivityType;
  title: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload: Record<string, any>;
  attempt: { score: number; correct: boolean; feedback: string; answer: Answer } | null;
}

export type Answer = Record<string, unknown>;

export interface AttemptResult {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  reward?: any;
  score: number;
  correct: boolean;
  feedback: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  reveal: Record<string, any>;
}

export interface BodyProps<A extends Answer = Answer> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload: Record<string, any>;
  answer: A;
  setAnswer: (a: A) => void;
  result: AttemptResult | null;
  locked: boolean;
  activityId?: number;
}
