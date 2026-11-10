import { useTranslation } from "react-i18next";

import type { Features } from "@/lib/types";

import { ExplainerPlayer } from "./ExplainerPlayer";
import { ListenBar } from "./Narration";
import { PodcastPlayer } from "./PodcastPlayer";

/** Listen, explainer video and podcast under a lesson, each shown only when the admin switched it on. */
export function LessonMedia({ features, md, title, keyPoints, lang, lessonId, listened, onListened }: {
  features: Features | undefined; md: string; title: string; keyPoints: string[]; lang: string; lessonId: number;
  listened: boolean; onListened: () => void;
}) {
  const { t } = useTranslation();
  const f = features ?? { podcast: false, explainer: false, listen: false };
  if (!f.listen && !f.explainer && !f.podcast) return null;
  return (
    <div className="space-y-3">
      {f.listen && <ListenBar md={md} title={title} keyPoints={keyPoints} lang={lang} lessonId={lessonId} onListened={onListened} />}
      {listened && (f.listen || f.podcast) && <p role="status" className="text-sm text-good">{t("lj.listened.done")}</p>}
      {f.explainer && <ExplainerPlayer lessonId={lessonId} lang={lang} />}
      {f.podcast && <PodcastPlayer lessonId={lessonId} lang={lang} onListened={onListened} />}
    </div>
  );
}
