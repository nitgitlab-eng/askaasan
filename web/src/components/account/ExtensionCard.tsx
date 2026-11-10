import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Puzzle, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { localeOf } from "@/i18n/languages";
import { Button, Card } from "@/components/ui";
import { api } from "@/lib/api";

type Device = { id: number; name: string; created_at: string; last_used_at: string | null };
type Pairing = { code: string; expires_at: string };

/** Pair the Aasan Companion browser extension with a short code, and list / remove connected browsers. */
export function ExtensionCard() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const [pairing, setPairing] = useState<Pairing | null>(null);
  // While a code is on screen, poll so the new browser appears (and the code hides) as soon as it's used.
  const [countAtStart, setCountAtStart] = useState(0);
  const { data } = useQuery({ queryKey: ["ext-devices"], queryFn: () => api<Device[]>("/api/ext/devices/"), refetchInterval: (q) => (pairing && (q.state.data?.length ?? 0) <= countAtStart ? 3000 : false) });
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const date = (s: string) => new Date(s).toLocaleDateString(localeOf(i18n.language), { day: "numeric", month: "short", year: "numeric" });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["ext-devices"] });

  // Once a new browser shows up, the code has been used — hide it.
  const claimed = !!pairing && (data?.length ?? 0) > countAtStart;
  const left = pairing && !claimed ? Math.max(0, Math.floor((new Date(pairing.expires_at).getTime() - now) / 1000)) : 0;
  useEffect(() => {
    if (!pairing) return;
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, [pairing]);


  async function connect() {
    setBusy(true);
    setMsg("");
    try {
      setCountAtStart(data?.length ?? 0);
      setPairing(await api<Pairing>("/api/ext/pair/start/", { method: "POST" }));
      setNow(Date.now());
    } catch {
      setMsg(t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }

  const mmss = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
  return (
    <Card className="space-y-3">
      <h2 className="flex items-center gap-2 font-display text-xl font-bold"><Puzzle className="h-5 w-5 text-accent" /> {t("extension.title")}</h2>
      <p className="text-sm text-muted">{t("extension.sub")}</p>
      {!data?.length ? <p className="text-sm text-muted">{t("extension.none")}</p> : (
        <ul className="divide-y divide-line">
          {data.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <p className="font-semibold">{d.name || "Browser"}</p>
                <p className="text-xs text-muted">{t("extension.connected", { date: date(d.created_at) })}{d.last_used_at ? ` · ${t("extension.used", { date: date(d.last_used_at) })}` : ""}</p>
              </div>
              <Button variant="outline" aria-label={t("extension.remove")} onClick={async () => {
                try { await api(`/api/ext/devices/${d.id}/`, { method: "DELETE" }); setMsg(t("extension.removed")); refresh(); }
                catch { setMsg(t("mentor.errors.generic")); }
              }}><Trash2 className="h-4 w-4" /></Button>
            </li>
          ))}
        </ul>
      )}
      {pairing && !claimed ? (
        <div className="space-y-2 rounded-2xl border-2 border-accent/40 bg-surface-2 p-4 text-center">
          <p className="text-sm text-muted">{t("extension.steps")}</p>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t("extension.codeLabel")}</p>
          {left > 0 ? (
            <>
              <p className="font-mono text-4xl font-extrabold tracking-[0.3em]" aria-live="polite">{pairing.code}</p>
              <p className="text-xs text-muted">{t("extension.expires", { time: mmss })}</p>
            </>
          ) : (
            <p className="text-sm text-bad">{t("extension.expired")}</p>
          )}
          {left === 0 && <Button onClick={connect} loading={busy}>{t("extension.newCode")}</Button>}
        </div>
      ) : (
        <Button onClick={connect} loading={busy}><Puzzle className="h-4 w-4" /> {t("extension.connect")}</Button>
      )}
      {msg && <p role="status" className="text-sm text-muted">{msg}</p>}
    </Card>
  );
}
