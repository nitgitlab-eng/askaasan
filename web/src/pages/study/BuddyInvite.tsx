import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { study } from "@/lib/study";
import { Kili } from "@/mascot/Kili";

export default function BuddyInvitePage() {
  const { t } = useTranslation();
  const { token = "" } = useParams();
  const { data, error } = useQuery({ queryKey: ["buddy-invite", token], queryFn: () => study.invitation(token), retry: false });
  const [state, setState] = useState<"idle" | "busy" | "ok" | "used">("idle");
  if (error) return <p className="p-8 text-muted">{t("buddy.invalid")}</p>;
  if (!data) return <p className="p-8 text-muted">{t("common.loading")}</p>;
  return (
    <div className="mx-auto max-w-md px-4 py-12">
      <Card className="flex flex-col items-center gap-3 text-center">
        <Kili mood={state === "ok" ? "celebrate" : "wave"} size={120} />
        <h1 className="font-display text-2xl font-extrabold">{t("buddy.inviteTitle", { name: data.inviter })}</h1>
        <p className="text-muted">{t("buddy.inviteSub")}</p>
        {data.self ? <p className="text-sm">{t("buddy.ownInvite")}</p> : state === "ok" || (data.accepted && state === "idle") ? (
          <Link to="/plan" className="font-semibold text-accent">{t("buddy.accepted")} →</Link>
        ) : state === "used" ? <p className="text-sm text-bad">{t("buddy.used")}</p> : (
          <Button loading={state === "busy"} onClick={async () => {
            setState("busy");
            try {
              await study.acceptBuddy(token);
              setState("ok");
            } catch (e) {
              setState(e instanceof ApiError && e.status === 409 ? "used" : "idle");
            }
          }}>{t("buddy.accept")}</Button>
        )}
      </Card>
    </div>
  );
}
