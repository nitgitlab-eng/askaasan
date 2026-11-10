import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, CalendarClock, Link2Off, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { confirmDialog } from "@/lib/dialog";
import { localeOf } from "@/i18n/languages";
import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { calendar, replanSummary, type CalendarProviderStatus } from "@/lib/calendar";
import { cn } from "@/lib/cn";

/** Connect Google Calendar / Outlook (read-only free/busy) and re-plan study blocks into real gaps. */
export function CalendarConnect() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["calendar-status"], queryFn: calendar.status });
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  if (!data) return null;
  const configured = data.providers.filter((p) => p.configured || p.connected);
  const anyConnected = data.providers.some((p) => p.connected);
  const err = (e: unknown) => {
    const code = e instanceof ApiError ? String(e.data?.code ?? "") : "";
    return t(`intgCal.errors.${code}`, { defaultValue: t("intgCal.errors.generic") });
  };

  async function connect(p: CalendarProviderStatus) {
    setBusy(p.provider);
    setNote(null);
    try {
      const { url } = await calendar.connect(p.provider);
      window.location.assign(url);
    } catch (e) {
      setNote({ ok: false, text: err(e) });
      setBusy(null);
    }
  }
  async function disconnect(p: CalendarProviderStatus) {
    if (!(await confirmDialog(t("intgCal.disconnectConfirm", { name: p.label }), { danger: true }))) return;
    setBusy(p.provider);
    try {
      qc.setQueryData(["calendar-status"], await calendar.disconnect(p.provider));
    } catch (e) {
      setNote({ ok: false, text: err(e) });
    } finally {
      setBusy(null);
    }
  }
  async function replan() {
    setBusy("replan");
    setNote(null);
    try {
      const r = await calendar.replan();
      qc.setQueryData(["calendar-status"], r);
      void qc.invalidateQueries({ queryKey: ["blocks"] });
      const kind = replanSummary(r);
      setNote({ ok: kind !== "reconnect", text: t(`intgCal.result.${kind}`, { n: kind === "unplaced" ? r.unplaced : r.moved, count: kind === "unplaced" ? r.unplaced : r.moved }) });
    } catch (e) {
      setNote({ ok: false, text: err(e) });
    } finally {
      setBusy(null);
    }
  }
  const when = (iso: string) => new Date(iso).toLocaleString(localeOf(i18n.language), { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

  return (
    <div className="space-y-2 rounded-2xl border-2 border-dashed border-line p-3">
      <div className="flex flex-wrap items-center gap-2">
        <CalendarClock className="h-5 w-5 text-accent" />
        <h3 className="flex-1 font-semibold">{t("intgCal.title")}</h3>
        <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] font-semibold text-muted">{t("intgCal.readOnly")}</span>
      </div>
      {configured.length === 0 ? (
        <p className="text-sm text-muted">{t("intgCal.noneConfigured")}</p>
      ) : (
        <>
          <p className="text-sm text-muted">{t("intgCal.intro")}</p>
          <ul className="flex flex-wrap gap-2">
            {data.providers.map((p) => (
              <li key={p.provider} className="flex flex-wrap items-center gap-2">
                {p.connected && !p.needs_reconnect ? (
                  <>
                    <span className="flex items-center gap-1 rounded-full bg-good/15 px-2.5 py-1 text-xs font-semibold text-good">
                      <CalendarCheck className="h-3.5 w-3.5" /> {p.label} · {t("intgCal.connected")}
                    </span>
                    {p.last_synced_at && <span className="text-xs text-muted">{t("intgCal.lastSynced", { when: when(p.last_synced_at) })}</span>}
                    <button onClick={() => void disconnect(p)} disabled={!!busy} className="flex items-center gap-1 rounded-lg px-1.5 py-0.5 text-xs text-muted hover:bg-surface-2">
                      <Link2Off className="h-3.5 w-3.5" /> {t("intgCal.disconnect")}
                    </button>
                  </>
                ) : p.configured ? (
                  <Button variant="outline" className="py-1.5 text-sm" loading={busy === p.provider} disabled={!!busy} onClick={() => void connect(p)}>
                    {t(p.needs_reconnect ? "intgCal.reconnect" : "intgCal.connect", { name: p.label })}
                  </Button>
                ) : (
                  <span className="text-xs text-muted">{t("intgCal.notConfigured", { name: p.label })}</span>
                )}
              </li>
            ))}
          </ul>
          {data.providers.filter((p) => p.needs_reconnect).map((p) => (
            <p key={p.provider} className="text-xs text-bad">{t("intgCal.needsReconnect", { name: p.label })}</p>
          ))}
          {anyConnected && (
            <Button className="py-1.5 text-sm" loading={busy === "replan"} disabled={!!busy} onClick={() => void replan()}>
              <RefreshCw className="h-4 w-4" /> {t("intgCal.replan")}
            </Button>
          )}
        </>
      )}
      {note && <p role="status" className={cn("rounded-xl px-3 py-2 text-sm", note.ok ? "bg-good/10 text-good" : "bg-bad/10 text-bad")}>{note.text}</p>}
    </div>
  );
}
