import { useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, CalendarX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Card } from "@/components/ui";
import { calendar, isProvider, parseCallback } from "@/lib/calendar";

/** Google / Microsoft send the learner back here (the redirect URI the owner registered); we finish the connect server-side. */
export default function CalendarCallbackPage() {
  const { t } = useTranslation();
  const { provider } = useParams();
  const qc = useQueryClient();
  const [parsed] = useState(() => parseCallback(window.location.search));
  const [state, setState] = useState<"working" | "done" | "denied" | "failed">(() =>
    !isProvider(provider) || parsed.kind === "invalid" ? "failed" : parsed.kind === "denied" ? "denied" : "working");
  const ran = useRef(false);

  useEffect(() => {
    window.history.replaceState(null, "", window.location.pathname); // keep the code out of history
    if (ran.current || parsed.kind !== "ok" || !isProvider(provider)) return; // the code is single-use; StrictMode would post it twice
    ran.current = true;
    calendar.callback(provider, parsed.code, parsed.state).then(
      (s) => { qc.setQueryData(["calendar-status"], s); setState("done"); },
      () => setState("failed"),
    );
  }, [provider, parsed, qc]);

  const ok = state === "done" || state === "working";
  return (
    <div className="mx-auto max-w-md px-4 py-12">
      <Card className="space-y-4 text-center">
        {ok ? <CalendarCheck className="mx-auto h-10 w-10 text-accent" /> : <CalendarX className="mx-auto h-10 w-10 text-bad" />}
        <p role="status" className="font-display text-xl font-bold">{t(`intgCal.callback.${state}`)}</p>
        {state !== "working" && <Link to="/plan" className="inline-block font-semibold text-accent">{t("intgCal.callback.back")}</Link>}
      </Card>
    </div>
  );
}
