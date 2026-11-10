import { ImagePlus, LifeBuoy, ShieldCheck, X } from "lucide-react";
import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Md } from "@/components/Md";
import { Button, Card } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { HELP_ERROR_MAX, HELP_IMAGE_MAX, HELP_IMAGE_TYPES, workshops } from "@/lib/workshops";

/**
 * "Stuck?" panel for setup and hands-on steps: paste (Ctrl+V), drop or choose a screenshot, and/or paste an error.
 * The image goes to the server for one AI answer only; nothing is kept here beyond a local preview.
 */
export function HelpPanel({ sessionId, className }: { sessionId: number; className?: string }) {
  const { t } = useTranslation();
  const [image, setImage] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [errorText, setErrorText] = useState("");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  // The local preview is the only copy kept on this side; it is released as soon as the image goes.
  useEffect(() => () => void (preview && URL.revokeObjectURL(preview)), [preview]);
  function pick(file: File | null) {
    setImage(file);
    setPreview(file && typeof URL.createObjectURL === "function" ? URL.createObjectURL(file) : null);
  }

  function take(file: File | undefined | null) {
    if (!file) return false;
    if (!HELP_IMAGE_TYPES.includes(file.type)) {
      setProblem(t("workshop.help.badType"));
      return true;
    }
    if (file.size > HELP_IMAGE_MAX) {
      setProblem(t("workshop.help.tooBig"));
      return true;
    }
    setProblem("");
    pick(file);
    return true;
  }

  const firstImage = (files: FileList | null | undefined) => Array.from(files ?? []).find((f) => f.type.startsWith("image/"));

  function onPaste(e: ClipboardEvent) {
    // Only a pasted picture is ours; pasted text lands in the field as usual.
    if (take(firstImage(e.clipboardData?.files))) e.preventDefault();
  }
  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    take(firstImage(e.dataTransfer?.files));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!image && !errorText.trim()) return setProblem(t("workshop.help.empty"));
    setBusy(true);
    setProblem("");
    try {
      const out = await workshops.help(sessionId, { image, error_text: errorText.trim(), note: "" });
      setReply(out.reply_md);
      pick(null);
    } catch (err) {
      const code = err instanceof ApiError ? String(err.data?.code ?? "") : "";
      const wait = err instanceof ApiError ? Number(err.data?.retry_after) : NaN;
      setProblem(t(`workshop.help.err.${code}`, { n: Number.isFinite(wait) && wait > 0 ? Math.ceil(wait / 60) : 1, defaultValue: t("workshop.help.failed") }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className={cn("space-y-3", className)} onPaste={onPaste}>
      <h2 className="flex items-center gap-2 font-display text-lg font-bold"><LifeBuoy className="h-5 w-5 text-accent" aria-hidden /> {t("workshop.help.title")}</h2>
      <form onSubmit={submit} className="space-y-3">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={onDrop}
          data-testid="help-drop"
          className={cn("rounded-2xl border-2 border-dashed p-3 text-center transition", over ? "border-accent bg-accent/10" : "border-line")}
        >
          {image ? (
            <div className="flex items-center gap-3 text-left">
              {preview && <img src={preview} alt="" className="h-16 w-24 rounded-lg object-cover" />}
              <p className="min-w-0 flex-1 truncate text-sm font-medium" title={image.name || undefined}>{image.name || t("workshop.help.pasted")}</p>
              <button type="button" onClick={() => pick(null)} className="rounded-lg p-1.5 text-muted hover:bg-surface-2" aria-label={t("workshop.help.remove")}><X className="h-4 w-4" /></button>
            </div>
          ) : (
            <button type="button" onClick={() => fileInput.current?.click()} className="flex w-full flex-col items-center gap-1 py-2 text-sm text-muted hover:text-ink">
              <ImagePlus className="h-6 w-6 text-accent" aria-hidden />
              {t("workshop.help.drop")}
            </button>
          )}
          <input
            ref={fileInput}
            type="file"
            accept={HELP_IMAGE_TYPES.join(",")}
            className="sr-only"
            aria-label={t("workshop.help.choose")}
            onChange={(e) => {
              take(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </div>
        <label className="block">
          <span className="text-sm font-medium">{t("workshop.help.errorLabel")}</span>
          <textarea value={errorText} onChange={(e) => setErrorText(e.target.value)} maxLength={HELP_ERROR_MAX} rows={3} placeholder={t("workshop.help.errorPh")}
            className="mt-1 w-full rounded-xl border-2 border-line bg-surface px-3 py-2 font-mono text-sm outline-none focus:border-accent" />
        </label>
        {problem && <p role="alert" className="text-sm text-bad">{problem}</p>}
        <Button type="submit" loading={busy} className="w-full">{t("workshop.help.send")}</Button>
        <p className="flex items-center gap-1.5 text-xs text-muted"><ShieldCheck className="h-4 w-4 shrink-0 text-good" aria-hidden /> {t("workshop.help.privacy")}</p>
      </form>
      {reply && (
        <div aria-live="polite" className="prose-chat rounded-2xl bg-accent/10 p-3">
          <p className="text-xs font-semibold text-accent">{t("workshop.help.reply")}</p>
          <Md ai>{reply}</Md>
        </div>
      )}
    </Card>
  );
}
