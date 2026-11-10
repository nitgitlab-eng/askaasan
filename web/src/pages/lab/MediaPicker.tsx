import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Sparkles, Upload, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { media, type MediaAsset } from "@/lib/media";

type Tab = "upload" | "generate" | "mine";

/** Upload, AI-generate, or reuse an image. Calls onPick with the stored asset. */
export function MediaPicker({ onPick, onClose, suggestion = "" }: { onPick: (a: MediaAsset) => void; onClose: () => void; suggestion?: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("upload");
  const [prompt, setPrompt] = useState(suggestion);
  const [alt, setAlt] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const { data: mine } = useQuery({ queryKey: ["my-media"], queryFn: media.mine, enabled: tab === "mine" });
  const done = (a: MediaAsset) => {
    void qc.invalidateQueries({ queryKey: ["my-media"] });
    onPick(a);
  };
  const run = async (fn: () => Promise<MediaAsset>) => {
    setBusy(true);
    setErr("");
    try {
      done(await fn());
    } catch (e) {
      const code = e instanceof ApiError ? String(e.data?.code ?? "") : "";
      setErr(t(`lab.media.err.${code}`, { defaultValue: t("mentor.errors.generic") }));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3 rounded-2xl border-2 border-accent/40 bg-surface p-4">
      <div className="flex items-center gap-1">
        {(["upload", "generate", "mine"] as Tab[]).map((k) => (
          <button key={k} type="button" onClick={() => setTab(k)} className={cn("rounded-xl px-3 py-1.5 text-sm font-semibold", tab === k ? "bg-accent text-accent-ink" : "hover:bg-surface-2")}>{t(`lab.media.${k}`)}</button>
        ))}
        <button type="button" onClick={onClose} className="ml-auto text-muted hover:text-ink" aria-label={t("lab.cancel")}><X className="h-5 w-5" /></button>
      </div>
      {tab !== "mine" && <input value={alt} onChange={(e) => setAlt(e.target.value)} maxLength={200} placeholder={t("lab.media.alt")} aria-label={t("lab.media.alt")} className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2 text-sm" />}
      {tab === "upload" && (
        <label className={cn("flex cursor-pointer items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-line p-6 font-semibold hover:border-accent", busy && "opacity-50")}>
          <Upload className="h-5 w-5" /> {busy ? t("common.saving") : t("lab.media.choose")}
          <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="sr-only" disabled={busy}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void run(() => media.upload(f, alt)); }} />
        </label>
      )}
      {tab === "generate" && (
        <div className="space-y-2">
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} maxLength={400} placeholder={t("lab.media.promptPh")} aria-label={t("lab.media.prompt")}
            className="w-full rounded-xl border-2 border-line bg-surface p-2 text-sm" />
          <p className="text-xs text-muted">{t("lab.media.genNote")}</p>
          <Button loading={busy} disabled={prompt.trim().length < 4} onClick={() => run(() => media.generate(prompt, alt || prompt.slice(0, 120)))}><Sparkles className="h-4 w-4" /> {t("lab.media.generateBtn")}</Button>
        </div>
      )}
      {tab === "mine" && (
        <div className="grid max-h-72 grid-cols-3 gap-2 overflow-y-auto sm:grid-cols-4">
          {mine?.length === 0 && <p className="col-span-full text-sm text-muted">{t("lab.media.none")}</p>}
          {mine?.map((a) => (
            <button key={a.id} type="button" onClick={() => done(a)} className="overflow-hidden rounded-xl border-2 border-line hover:border-accent" title={a.alt || a.prompt}>
              <img src={a.url} alt={a.alt} className="aspect-square w-full object-cover" loading="lazy" />
            </button>
          ))}
        </div>
      )}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </div>
  );
}

/** Small control: shows the current image with change/remove, or an "Add image" button. */
export function ImageField({ value, onChange, suggestion }: { value?: string; onChange: (url: string) => void; suggestion?: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-2">
      {value ? (
        <div className="flex items-start gap-3">
          <img src={value} alt="" className="h-24 w-24 rounded-xl border border-line object-cover" />
          <div className="flex flex-col gap-1">
            <Button variant="outline" className="py-1 text-sm" onClick={() => setOpen(true)}>{t("lab.media.change")}</Button>
            <Button variant="ghost" className="py-1 text-sm text-bad" onClick={() => onChange("")}>{t("lab.remove")}</Button>
          </div>
        </div>
      ) : !open && <Button variant="outline" className="py-1.5 text-sm" onClick={() => setOpen(true)}><ImagePlus className="h-4 w-4" /> {t("lab.media.add")}</Button>}
      {open && <MediaPicker suggestion={suggestion} onClose={() => setOpen(false)} onPick={(a) => { onChange(a.url); setOpen(false); }} />}
    </div>
  );
}
