import { useQuery } from "@tanstack/react-query";
import { Gauge } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Card } from "@/components/ui";
import { learner } from "@/lib/learner";

const pct = (x?: number | null) => (x == null ? "—" : `${Math.round(x * 100)}%`);

/** My checkpoints: before/after scores for every course and the learning gain. */
export default function CheckpointsPage() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["my-checkpoints"], queryFn: learner.myCheckpoints });
  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <header>
        <h1 className="flex items-center gap-2 font-display text-3xl font-extrabold"><Gauge className="h-7 w-7 text-accent" /> {t("checkpoint.mine")}</h1>
        <p className="text-muted">{t("checkpoint.mineSub")}</p>
      </header>
      {!data ? <p className="text-muted">{t("common.loading")}</p> : !data.length ? <Card><p>{t("checkpoint.none")}</p><Link to="/learn" className="font-semibold text-accent">{t("learn.start")} →</Link></Card> : (
        <Card>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted"><tr><th className="py-1">{t("checkpoint.course")}</th><th>{t("checkpoint.before")}</th><th>{t("checkpoint.after")}</th><th>{t("checkpoint.gain")}</th></tr></thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.course.id} className="border-t border-line">
                  <td className="py-2"><Link to={`/learn/${r.course.id}`} className="font-semibold hover:text-accent">{r.course.emoji} {r.course.title}</Link></td>
                  <td className="tabular-nums">{pct(r.pre?.score)}</td>
                  <td className="tabular-nums">{pct(r.post?.score)}</td>
                  <td className={r.gain == null ? "" : r.gain >= 0 ? "font-semibold text-good" : "font-semibold text-bad"}>{r.gain == null ? "—" : `${r.gain >= 0 ? "+" : ""}${Math.round(r.gain * 100)} pts`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
