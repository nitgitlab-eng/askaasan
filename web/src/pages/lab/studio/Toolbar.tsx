import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, History, MessageSquareText, Redo2, Save, Undo2, Library as LibraryIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { confirmDialog } from "@/lib/dialog";
import { localeOf } from "@/i18n/languages";
import { Button, Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import { downloadFile } from "@/lib/download";
import type { LabCourse } from "@/lib/lab";
import { orgs } from "@/lib/orgs";
import { studio } from "@/lib/studio";
import { useMe } from "@/lib/useMe";

/** Undo/redo (⌘Z / ⇧⌘Z), named versions, export (JSON · YAML · PowerPoint), template sharing, panels. */
export function StudioToolbar({ c, set, panel, setPanel }: { c: LabCourse; set: (c: LabCourse) => void; panel: string; setPanel: (p: string) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const [open, setOpen] = useState<"" | "versions" | "export" | "template">("");
  const [busy, setBusy] = useState(false);
  const h = c.history;

  async function step(dir: "undo" | "redo") {
    if (busy) return;
    setBusy(true);
    try {
      set(await (dir === "undo" ? studio.undo(c.id) : studio.redo(c.id)));
      void qc.invalidateQueries({ queryKey: ["lab-lesson"] });
      void qc.invalidateQueries({ queryKey: ["versions", c.id] });
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "z" || tag === "INPUT" || tag === "TEXTAREA") return;
      e.preventDefault();
      void step(e.shiftKey ? "redo" : "undo");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const btn = "flex items-center gap-1.5 rounded-xl border-2 border-line px-3 py-1.5 text-sm font-semibold hover:border-accent disabled:opacity-40";
  return (
    <Card className="space-y-3 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <button className={btn} disabled={!h?.can_undo || busy} onClick={() => void step("undo")} title={h?.undo_label ? t("studio.undoWhat", { what: h.undo_label }) : ""}>
          <Undo2 className="h-4 w-4" /> {t("studio.undo")}
        </button>
        <button className={btn} disabled={!h?.can_redo || busy} onClick={() => void step("redo")} title={h?.redo_label ? t("studio.redoWhat", { what: h.redo_label }) : ""}>
          <Redo2 className="h-4 w-4" /> {t("studio.redo")}
        </button>
        <button className={cn(btn, open === "versions" && "border-accent")} onClick={() => setOpen(open === "versions" ? "" : "versions")}><History className="h-4 w-4" /> {t("studio.versions")}</button>
        <button className={cn(btn, open === "export" && "border-accent")} onClick={() => setOpen(open === "export" ? "" : "export")}><Download className="h-4 w-4" /> {t("studio.export")}</button>
        <button className={cn(btn, open === "template" && "border-accent")} onClick={() => setOpen(open === "template" ? "" : "template")}><LibraryIcon className="h-4 w-4" /> {t("studio.template")}{c.template?.scope ? " ✓" : ""}</button>
        <span className="flex-1" />
        <button className={cn(btn, panel === "grounding" && "border-accent bg-accent/10")} onClick={() => setPanel(panel === "grounding" ? "" : "grounding")}>📚 {t("studio.grounding")}</button>
        <button className={cn(btn, panel === "kili" && "border-accent bg-accent/10")} onClick={() => setPanel(panel === "kili" ? "" : "kili")}><MessageSquareText className="h-4 w-4" /> {t("studio.buildWithKili")}</button>
      </div>
      {h?.undo_label && <p className="text-xs text-muted">{t("studio.lastChange", { what: h.undo_label })} · {t("studio.shortcut")}</p>}
      {open === "versions" && <Versions c={c} set={set} />}
      {open === "export" && (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => void downloadFile(studio.urls.pptx(c.id), "course.pptx")}>📊 {t("studio.pptx")}</Button>
          <Button variant="outline" onClick={() => void downloadFile(studio.urls.exportJson(c.id), "course.json")}>{"{ }"} JSON</Button>
          <Button variant="outline" onClick={() => void downloadFile(studio.urls.exportYaml(c.id), "course.yaml")}>YAML</Button>
          <p className="w-full text-xs text-muted">{t("studio.exportHint")}</p>
        </div>
      )}
      {open === "template" && <TemplateScope c={c} set={set} staff={!!me?.is_staff} />}
    </Card>
  );
}

function Versions({ c, set }: { c: LabCourse; set: (c: LabCourse) => void }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["versions", c.id], queryFn: () => studio.history(c.id) });
  const [label, setLabel] = useState("");
  const when = (iso: string) => new Date(iso).toLocaleString(localeOf(i18n.language), { dateStyle: "medium", timeStyle: "short" });
  return (
    <div className="space-y-2">
      <form className="flex gap-2" onSubmit={async (e) => { e.preventDefault(); qc.setQueryData(["versions", c.id], await studio.saveVersion(c.id, label)); setLabel(""); }}>
        <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={120} placeholder={t("studio.versionName")} aria-label={t("studio.versionName")}
          className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-1.5 text-sm outline-none focus:border-accent" />
        <Button type="submit" variant="outline"><Save className="h-4 w-4" /> {t("studio.saveVersion")}</Button>
      </form>
      {!data?.versions.length && <p className="text-sm text-muted">{t("studio.noVersions")}</p>}
      <ul className="divide-y divide-line">
        {data?.versions.map((v) => (
          <li key={v.id} className="flex items-center gap-2 py-1.5 text-sm">
            <span className="min-w-0 flex-1"><b>{v.label}</b> <span className="text-muted">· {when(v.created_at)} · {t("studio.lessonsN", { count: v.lessons })}</span></span>
            <button className="font-semibold text-accent" onClick={async () => { if (await confirmDialog(t("studio.confirmRestore", { name: v.label }))) { set(await studio.restoreVersion(c.id, v.id)); void qc.invalidateQueries({ queryKey: ["lab-lesson"] }); } }}>{t("studio.restore")}</button>
            <button className="text-muted hover:text-bad" onClick={async () => { await studio.deleteVersion(c.id, v.id); void qc.invalidateQueries({ queryKey: ["versions", c.id] }); }} aria-label={t("lab.delete")}>✕</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TemplateScope({ c, set, staff }: { c: LabCourse; set: (c: LabCourse) => void; staff: boolean }) {
  const { t } = useTranslation();
  const { data: myOrgs } = useQuery({ queryKey: ["orgs"], queryFn: orgs.list });
  const managed = (myOrgs ?? []).filter((o) => o.role !== "learner");
  const cur = c.template?.scope ? (c.template.scope === "org" ? `org:${c.template.org}` : c.template.scope) : "";
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <label className="flex items-center gap-2">{t("studio.shareAsTemplate")}
        <select value={cur} onChange={async (e) => { const v = e.target.value; set(await studio.setTemplate(c.id, v.startsWith("org:") ? "org" : v, v.startsWith("org:") ? v.slice(4) : undefined)); }}
          className="rounded-xl border-2 border-line bg-surface px-2 py-1.5">
          <option value="">{t("studio.notTemplate")}</option>
          <option value="personal">{t("studio.tplPersonal")}</option>
          {managed.map((o) => <option key={o.slug} value={`org:${o.slug}`}>{t("studio.tplOrg", { org: o.name })}</option>)}
          {staff && <option value="global">{t("studio.tplGlobal")}</option>}
        </select>
      </label>
      <span className="text-xs text-muted">{t("studio.templateHint")}</span>
    </div>
  );
}
