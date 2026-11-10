import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { pop, useDialog, type Request } from "@/lib/dialog";

import { Button } from "./ui";

/** The app's own confirm / prompt / alert (see lib/dialog.ts), mounted once at the app root. */
export function DialogHost() {
  const req = useDialog((s) => s.queue[0]);
  return req ? <DialogView key={req.id} req={req} /> : null;
}

function DialogView({ req }: { req: Request }) {
  const { t } = useTranslation();
  const [text, setText] = useState(req.kind === "prompt" ? (req.defaultValue ?? "") : "");
  const input = useRef<HTMLInputElement>(null);
  const okBtn = useRef<HTMLButtonElement>(null);
  const close = (ok: boolean) => {
    pop();
    if (req.kind === "confirm") req.resolve(ok);
    else if (req.kind === "prompt") req.resolve(ok ? text.trim() : null);
    else req.resolve();
  };
  useEffect(() => {
    (req.kind === "prompt" ? input.current : okBtn.current)?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    close(true);
  };
  return (
    <div className="fixed inset-0 z-[120] flex items-end justify-center bg-black/40 p-4 sm:items-center" onClick={() => close(false)}>
      <form
        role={req.kind === "alert" ? "alertdialog" : "dialog"}
        aria-modal="true"
        aria-labelledby="app-dialog-msg"
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md space-y-4 rounded-3xl bg-surface p-6 shadow-xl"
      >
        <p id="app-dialog-msg" className="whitespace-pre-line">{req.message}</p>
        {req.kind === "prompt" && (
          <input ref={input} value={text} onChange={(e) => setText(e.target.value)} aria-labelledby="app-dialog-msg" className="w-full rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent" />
        )}
        <div className="flex justify-end gap-2">
          {req.kind !== "alert" && <Button type="button" variant="ghost" onClick={() => close(false)}>{t("dialog.cancel")}</Button>}
          <Button ref={okBtn} type="submit" className={req.kind === "confirm" && req.danger ? "bg-bad text-white" : undefined} disabled={req.kind === "prompt" && !req.allowEmpty && !text.trim()}>
            {(req.kind !== "alert" && req.ok) || t("dialog.ok")}
          </Button>
        </div>
      </form>
    </div>
  );
}
