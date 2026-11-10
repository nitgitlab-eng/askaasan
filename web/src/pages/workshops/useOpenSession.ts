import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { localeOf } from "@/i18n/languages";
import { ApiError } from "@/lib/api";
import { workshops, type Run } from "@/lib/workshops";

const KNOWN = ["payment_required", "not_enrolled", "too_early", "too_late", "run_cancelled", "run_full", "run_closed"];
const errorKey = (e: unknown) => {
  if (!(e instanceof ApiError)) return "generic";
  const code = String(e.data?.code ?? "");
  if (KNOWN.includes(code)) return code;
  if (e.status === 402) return "payment_required";
  return e.status === 403 || e.status === 409 ? "closed" : "generic";
};

/** Opens (or creates) the learner's session for a run and goes there; join errors come back as a message. */
export function useOpenSession() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function open(run: Pick<Run, "id" | "session_id">) {
    setBusy(true);
    setErr("");
    try {
      navigate(`/workshops/session/${run.session_id ?? (await workshops.openSession(run.id)).id}`);
    } catch (e) {
      const opens = e instanceof ApiError && typeof e.data?.opens_at === "string" ? new Date(e.data.opens_at) : null;
      setErr(t(`workshop.list.err.${errorKey(e)}`, { time: opens ? opens.toLocaleString(localeOf(i18n.language), { dateStyle: "medium", timeStyle: "short" }) : "" }));
      setBusy(false);
    }
  }
  return { open, busy, err };
}
