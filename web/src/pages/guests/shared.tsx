import { Download, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { downloadFile } from "@/lib/download";
import { authBlobUrl, guests } from "@/lib/guests";

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const { t } = useTranslation();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4" onClick={onClose}>
      <div role="dialog" aria-modal aria-label={title} className="max-h-[92dvh] w-full max-w-lg overflow-y-auto rounded-t-3xl bg-surface p-5 shadow-xl sm:rounded-3xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="font-display text-xl font-bold">{title}</h2>
          <button aria-label={t("guest.close")} onClick={onClose} className="rounded-full p-1 hover:bg-surface-2"><X className="h-5 w-5" /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function QrPreview({ linkId, slug }: { linkId: number; slug: string }) {
  const { t } = useTranslation();
  const [src, setSrc] = useState<string | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let url: string | null = null;
    authBlobUrl(guests.qrUrl(linkId, "svg")).then((u) => { url = u; setSrc(u); }).catch(() => setErr(true));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [linkId]);
  return (
    <div className="flex flex-col items-center gap-3">
      {src ? <img src={src} alt={t("guest.qrAlt")} className="h-56 w-56 rounded-xl border border-line bg-white" /> : <p className="text-sm text-muted">{err ? t("guest.error") : t("common.loading")}</p>}
      <div className="flex flex-wrap justify-center gap-2">
        <Button variant="outline" className="py-1.5 text-sm" onClick={() => void downloadFile(guests.qrUrl(linkId, "svg"), `guest-${slug}.svg`)}><Download className="h-4 w-4" /> SVG</Button>
        <Button variant="outline" className="py-1.5 text-sm" onClick={() => void downloadFile(guests.qrUrl(linkId, "png"), `guest-${slug}.png`)}><Download className="h-4 w-4" /> PNG</Button>
      </div>
    </div>
  );
}
