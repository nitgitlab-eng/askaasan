import type { TFunction } from "i18next";

export interface ArtifactItem {
  kind: "phrase" | "heading" | "link" | "images";
  value: string;
  min_count: number;
}

export const isHttpsUrl = (u: string | undefined) => /^https:\/\/[^\s/?#@]+\.[^\s/?#@]+(?:[/?#]\S*)?$/i.test((u ?? "").trim());

export function artifactItemLabel(t: TFunction, c: ArtifactItem): string {
  if (c.kind === "link" && !c.value) return t("lx.artifact.kinds.linkAny", { count: c.min_count });
  if (c.kind === "images") return t("lx.artifact.kinds.images", { count: c.min_count });
  return t(`lx.artifact.kinds.${c.kind}`, { value: c.value });
}
