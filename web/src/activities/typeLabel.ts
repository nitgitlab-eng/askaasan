/** i18n key for an activity type's display name (newer types live in their own i18n sections). */
export function typeLabelKey(type: string): string {
  return type === "artifact_check" ? "lx.types.artifact_check" : `lesson.types.${type}`;
}
