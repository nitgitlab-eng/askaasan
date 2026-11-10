import type { ComponentType } from "react";

import { CategorizationBody, ChoiceBody, CodeBody, FillBlankBody, MatchingBody, OpenInputBody, SequencingBody } from "./bodies";
import { ConceptMapBody, DecisionTreeBody, SlidesBody, TaskBody, VizBody } from "./bodies2";
import { BrowserTaskBody, HotspotBody, MapBody, RolePlayBody, VideoBody } from "./bodies3";
import { ArtifactCheckBody } from "./bodiesLx";
import { isHttpsUrl } from "./lxArtifact";
import type { ActivityType, Answer, BodyProps } from "./types";

interface Def {
  // Each body narrows its own answer shape; the card treats answers generically.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Body: ComponentType<BodyProps<any>>;
  /** Ready to submit? Keeps the Check button honest. */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ready: (answer: any, payload: any) => boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  initial?: (payload: any) => Answer;
  icon: string;
}

export const REGISTRY: Record<ActivityType, Def> = {
  quiz: { Body: ChoiceBody, ready: (a) => (a.selected ?? []).length > 0, icon: "❓" },
  diagram: { Body: ChoiceBody, ready: (a) => (a.selected ?? []).length > 0, icon: "🗺️" },
  fill_blank: {
    Body: FillBlankBody,
    ready: (a, p) => (p.blank_ids as string[]).every((id) => (a.blanks?.[id] ?? "").trim()),
    icon: "✏️",
  },
  sequencing: {
    Body: SequencingBody,
    ready: () => true,
    initial: (p) => ({ order: (p.items as { id: string }[]).map((i) => i.id) }),
    icon: "🔢",
  },
  categorization: {
    Body: CategorizationBody,
    ready: (a, p) => Object.keys(a.assign ?? {}).length === p.items.length,
    icon: "🧺",
  },
  matching: { Body: MatchingBody, ready: (a, p) => Object.keys(a.pairs ?? {}).length === p.left.length, icon: "🔗" },
  open_input: { Body: OpenInputBody, ready: (a) => (a.text ?? "").trim().length >= 3, icon: "💬" },
  code: { Body: CodeBody, ready: (a, p) => (a.code ?? p.starter_code ?? "").trim().length > 0, icon: "🐍" },
  slides: { Body: SlidesBody, ready: (a) => (a.selected ?? []).length > 0, icon: "🎬" },
  concept_map: { Body: ConceptMapBody, ready: (a, p) => p.links.every((l: { id: string }) => a.labels?.[l.id]), icon: "🕸️" },
  viz: { Body: VizBody, ready: (a) => (a.selected ?? []).length > 0, icon: "📈" },
  decision_tree: {
    Body: DecisionTreeBody,
    // Ready once the path reaches an ending.
    ready: (a, p) => {
      let node = p.start;
      for (const cid of a.path ?? []) node = p.nodes[node]?.choices.find((c: { id: string }) => c.id === cid)?.next ?? "";
      return (a.path ?? []).length > 0 && !node;
    },
    icon: "🌳",
  },
  task: { Body: TaskBody, ready: (a) => (a.text ?? "").trim().length >= 10, icon: "🛠️" },
  map: { Body: MapBody, ready: (a, p) => p.targets.every((x: { id: string }) => a.points?.[x.id]), icon: "🗺️" },
  hotspot: { Body: HotspotBody, ready: (a, p) => p.labels.every((x: { id: string }) => a.points?.[x.id]), icon: "🎯" },
  video: { Body: VideoBody, ready: (a, p) => p.checkpoints.every((c: { id: string }) => (a.answers?.[c.id] ?? []).length), icon: "📺" },
  browser_task: { Body: BrowserTaskBody, ready: (a) => !!a.image, icon: "🖥️" },
  roleplay: { Body: RolePlayBody, ready: () => true, icon: "🎭" },
  artifact_check: { Body: ArtifactCheckBody, ready: (a) => isHttpsUrl(a.url), icon: "🌐" },
};
