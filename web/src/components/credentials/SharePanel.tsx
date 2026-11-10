import { useQuery } from "@tanstack/react-query";
import { Copy, Image as ImageIcon, Sparkles } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Segmented } from "@/components/ui";
import { localeOf } from "@/i18n/languages";
import { ApiError } from "@/lib/api";
import { composePost, credentials, type ShareFacts, type ShareFormat, type ShareSource } from "@/lib/credentials";
import { saveBlob, shareSvg, svgToPng, type ShareCard } from "@/lib/shareImage";

/** The share image is built only from facts the server returned for this learner — nothing typed by the AI. */
function useShareCard() {
  const { t, i18n } = useTranslation();
  return (f: ShareFacts): ShareCard => {
    if (f.kind === "certificate") {
      const date = new Date(f.date).toLocaleDateString(localeOf(i18n.language), { dateStyle: "long" });
      return { eyebrow: t(`cred.img.eyebrow.${f.type}`), title: f.certificate, badge: "✓",
        lines: [f.name, t("cred.img.issuedBy", { issuer: f.issuer_type === "organisation" ? `${f.issuer} (${t("credSurvey2.orgOnAasan")})` : f.issuer }), date, ...(f.score_pct != null ? [t("cred.img.score", { pct: f.score_pct })] : [])],
        footer: f.verify_url };
    }
    const s = f.stats;
    const lines = [
      s.lessons ? t("cred.img.lessons", { count: s.lessons }) : "",
      s.minutes ? t("cred.img.minutes", { count: s.minutes }) : "",
      s.best_streak || s.streak ? t("cred.img.streak", { n: s.best_streak || s.streak }) : "",
      f.certificates.length ? t("cred.img.certs", { count: f.certificates.length }) : "",
    ].filter(Boolean);
    return { eyebrow: t("cred.img.eyebrow.review"), title: f.courses.length ? f.courses.slice(0, 2).map((c) => c.title).join(" · ") : f.name,
      badge: "★", lines: [f.name, ...lines], footer: t("cred.img.footer") };
  };
}

/** "Share your progress": Kili writes a short manager summary or a LinkedIn post from the learner's own facts (charged),
 *  editable before copying; plus a share image (SVG/PNG) drawn in the browser. */
export function SharePanel({ src }: { src: ShareSource }) {
  const { t } = useTranslation();
  const card = useShareCard();
  const [fmt, setFmt] = useState<ShareFormat>("manager");
  const [text, setText] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState(false);
  const facts = useQuery({ queryKey: ["share-facts", src.source, src.certificateId], queryFn: () => credentials.facts(src) });

  async function write() {
    setBusy(true);
    setErr("");
    try {
      const r = await credentials.share(src, fmt);
      setText(r.text);
      setTags(r.hashtags);
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 429 ? t("paths.budget") : t("mentor.errors.generic"));
    } finally {
      setBusy(false);
    }
  }
  async function image(kind: "png" | "svg") {
    if (!facts.data) return;
    const svg = shareSvg(card(facts.data));
    const name = src.source === "certificate" ? "aasan-certificate" : "aasan-progress";
    try {
      saveBlob(kind === "svg" ? new Blob([svg], { type: "image/svg+xml" }) : await svgToPng(svg), `${name}.${kind}`);
    } catch {
      setErr(t("mentor.errors.generic"));
    }
  }
  return (
    <div className="space-y-3 rounded-xl border-2 border-dashed border-accent/40 p-3 print:hidden">
      <p className="font-semibold">{t("cred.share.title")}</p>
      <Segmented label={t("cred.share.format")} value={fmt} onChange={(v) => { setFmt(v); setText(""); setTags([]); }}
        options={[{ value: "manager", label: t("cred.share.manager") }, { value: "linkedin", label: t("cred.share.linkedin") }]} />
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" className="py-1.5 text-sm" loading={busy} onClick={() => void write()}><Sparkles className="h-4 w-4" /> {text ? t("cred.share.rewrite") : t("cred.share.write")}</Button>
        <span className="text-xs text-muted">{t("cred.share.aiNote")}</span>
      </div>
      {text && (
        <>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={8} aria-label={t("cred.share.edit")} className="w-full rounded-xl border-2 border-line bg-surface p-2 text-sm" />
          {!!tags.length && <p className="text-sm text-accent">{tags.map((h) => `#${h}`).join(" ")}</p>}
          <p className="text-xs text-muted">{t("cred.share.check")}</p>
          <Button className="py-1.5 text-sm" onClick={() => { void navigator.clipboard.writeText(composePost(text, tags)); setCopied(true); setTimeout(() => setCopied(false), 2000); }}>
            <Copy className="h-4 w-4" /> {copied ? t("cred.share.copied") : t("cred.share.copy")}
          </Button>
        </>
      )}
      {facts.data && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-2 text-sm">
          <ImageIcon className="h-4 w-4 text-muted" /> <span className="text-muted">{t("cred.share.image")}</span>
          <button type="button" className="font-semibold text-accent" onClick={() => void image("png")}>PNG</button>
          <button type="button" className="font-semibold text-accent" onClick={() => void image("svg")}>SVG</button>
        </div>
      )}
      {err && <p role="alert" className="text-sm text-bad">{err}</p>}
    </div>
  );
}
