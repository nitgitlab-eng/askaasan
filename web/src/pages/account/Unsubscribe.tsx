import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "@/lib/api";
import { Kili } from "@/mascot/Kili";

/** One-click unsubscribe from an email link — works without signing in. */
export default function Unsubscribe() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const [state, setState] = useState<"working" | "done" | "bad">("working");
  const [cat, setCat] = useState("");
  useEffect(() => {
    api<{ ok: boolean; category: string }>("/api/users/unsubscribe/", { method: "POST", json: { t: params.get("t") ?? "" } })
      .then((r) => { setCat(r.category); setState("done"); })
      .catch(() => setState("bad"));
  }, [params]);
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
      <Kili mood={state === "bad" ? "confused" : "wave"} size={110} />
      {state === "working" && <p className="text-muted">{t("common.loading")}</p>}
      {state === "done" && (
        <>
          <h1 className="font-display text-2xl font-bold">{t("account.unsubDone")}</h1>
          <p className="text-muted">{t(`account.notif.${cat}`)}: {t("account.unsubOff")}</p>
        </>
      )}
      {state === "bad" && <p className="font-semibold">{t("account.unsubBad")}</p>}
      <Link to="/account" className="font-semibold text-accent underline">{t("account.unsubManage")}</Link>
    </main>
  );
}
