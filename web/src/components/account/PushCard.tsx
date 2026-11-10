import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card, Toggle } from "@/components/ui";
import { deviceState, disablePush, enablePush, pushKey, pushStatus, pushSupported, resumeReminders, sendTestPush, type PushState } from "@/lib/push";
import { useMe, useUpdatePreferences } from "@/lib/useMe";

const PUSH_KINDS = ["push_study", "push_streak", "push_reviews", "push_workshops", "push_teacher", "push_plan"] as const;

/** Account → notifications on this device: turn on, choose kinds, send a test, turn off. Hidden when the server has no push keys. */
export function PushCard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const update = useUpdatePreferences();
  const supported = pushSupported();
  const { data: status } = useQuery({ queryKey: pushKey, queryFn: pushStatus, enabled: supported });
  const [state, setState] = useState<PushState | null>(supported ? null : "unsupported");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!supported || !status) return;
    let live = true;
    void deviceState(status).then((s) => live && setState(s));
    return () => {
      live = false;
    };
  }, [status, supported]);

  useEffect(() => {
    // The back-off notice links to /account#push: bring the card into view once it has rendered.
    if (state && state !== "off_server" && window.location.hash === "#push") document.getElementById("push")?.scrollIntoView?.({ block: "start" });
  }, [state]);

  if (state === null || state === "off_server") return null;

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setMsg("");
    try {
      await fn();
    } catch {
      setMsg(t("push.failed"));
    } finally {
      setBusy(false);
      void qc.invalidateQueries({ queryKey: pushKey });
    }
  }

  const prefs = me?.preferences.notifications;
  const backoff = status?.reminders?.state;
  return (
    <Card id="push" className="space-y-3 scroll-mt-20">
      <h2 className="flex items-center gap-2 font-display text-lg font-bold"><BellRing className="h-5 w-5 text-accent" /> {t("push.title")}</h2>
      <p className="text-sm text-muted">{t("push.sub")}</p>
      {state === "unsupported" && <p className="text-sm">{t("push.unsupported")}</p>}
      {state === "denied" && <p className="text-sm">{t("push.denied")}</p>}
      {state === "off" && (
        <Button loading={busy} onClick={() => run(async () => setState(await enablePush(status?.public_key ?? "")))}>{t("push.turnOn")}</Button>
      )}
      {state === "on" && (
        <>
          <p className="text-sm font-semibold text-good">{t("push.on")}</p>
          {(backoff === "paused" || backoff === "alternate") && (
            <div role="status" className="space-y-2 rounded-xl border border-line bg-surface-2 p-3 text-sm">
              <p>{t(backoff === "paused" ? "push.backoffPaused" : "push.backoffAlternate")}</p>
              <Button variant="outline" disabled={busy} onClick={() => run(async () => { await resumeReminders(); setMsg(t("push.resumed")); })}>{t("push.resume")}</Button>
            </div>
          )}
          {prefs && PUSH_KINDS.map((k) => (
            <div key={k} className="flex items-center justify-between gap-3">
              <div><p className="font-medium">{t(`account.notif.${k}`)}</p><p className="text-xs text-muted">{t(`account.notifSub.${k}`)}</p></div>
              <Toggle checked={prefs[k] ?? true} onChange={(v) => update.mutate({ notifications: { [k]: v } })} label={t(`account.notif.${k}`)} />
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={busy} onClick={() => run(async () => { await sendTestPush(); setMsg(t("push.testSent")); })}>{t("push.test")}</Button>
            <Button variant="outline" disabled={busy} onClick={() => run(async () => { await disablePush(); setState("off"); })}>{t("push.turnOff")}</Button>
          </div>
        </>
      )}
      {msg && <p role="status" className="text-sm">{msg}</p>}
    </Card>
  );
}
