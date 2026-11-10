import { useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { roleplay, type CoachHint, type CoachState } from "@/lib/roleplay";

import { needsTrack } from "./coachLogic";

const HINTS = 3;

/** Live tracker + hints for one role-play session. Scores each learner turn once the character has replied. */
export function useLiveCoach(sessionId: number, initial: CoachState | undefined, learnerTurns: number, busy: boolean) {
  const [state, setState] = useState<CoachState | null>(initial ?? null);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<"budget" | "failed" | null>(null);
  const [hint, setHint] = useState<CoachHint | null>(null);
  const [hintBusy, setHintBusy] = useState(false);
  const [hintError, setHintError] = useState<"limit" | "budget" | "failed" | null>(null);
  const tracked = useRef(initial?.progression.length ?? 0);

  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!needsTrack(learnerTurns, tracked.current, busy)) return;
    tracked.current = learnerTurns;
    // Not cancelled when the learner sends the next reply: the result is still the newest scored state.
    setUpdating(true);
    roleplay
      .track(sessionId)
      .then((s) => {
        if (!mounted.current) return;
        setState((prev) => (prev && prev.progression.length > s.progression.length ? prev : s)); // ignore a slower, older reply
        setError(null);
      })
      .catch((e) => mounted.current && setError(e instanceof ApiError && e.status === 429 ? "budget" : "failed"))
      .finally(() => mounted.current && setUpdating(false));
  }, [sessionId, learnerTurns, busy]);

  async function askHint() {
    setHintBusy(true);
    setHintError(null);
    try {
      const r = await roleplay.hint(sessionId);
      setHint(r.hint);
      setState((s) => (s ? { ...s, hints: [...s.hints, r.hint], hints_used: r.hints_used, hints_left: r.hints_left } : s));
    } catch (e) {
      const code = e instanceof ApiError ? e.data?.code : null;
      setHintError(code === "hint_limit" ? "limit" : code === "ai_budget_exceeded" ? "budget" : "failed");
      if (code === "hint_limit") setState((s) => (s ? { ...s, hints_left: 0 } : s));
    } finally {
      setHintBusy(false);
    }
  }

  return { state, updating, error, hint, hintBusy, hintError, askHint, closeHint: () => setHint(null), hintsLeft: state?.hints_left ?? HINTS };
}
