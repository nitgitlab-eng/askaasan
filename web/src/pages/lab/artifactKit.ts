// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Src = Record<string, any>;

export const emptyArtifactCheck = (): Src => ({
  type: "artifact_check", title: "", prompt: "", steps: [], show_checklist: true, explanation: "",
  checks: [{ kind: "heading", value: "", min_count: 1 }],
});
