import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { useMe, useUpdatePreferences } from "@/lib/useMe";
import { Kili } from "@/mascot/Kili";

import { STEPS, useTour } from "./tourStore";


export function TourHost() {
  const { t } = useTranslation();
  const { name, step, set } = useTour();
  const { data: me } = useMe();
  const update = useUpdatePreferences();
  const [rect, setRect] = useState<DOMRect | null>(null);
  const card = useRef<HTMLDivElement>(null);
  const steps = name ? STEPS[name] : [];
  const cur = steps[step];

  useLayoutEffect(() => {
    if (!cur?.sel) return;
    const el = document.querySelector(cur.sel);
    if (!el || !(el as HTMLElement).offsetParent) {
      set(name, step + 1); // not on this screen (role, small screen…) → next step
      return;
    }
    el.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
    const measure = () => setRect(el.getBoundingClientRect());
    measure();
    const id = setTimeout(measure, 350);
    // Follow the target while the page (or any scrolling panel) moves, once per frame.
    let frame = 0;
    const follow = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    window.addEventListener("resize", follow);
    window.addEventListener("scroll", follow, { capture: true, passive: true });
    return () => {
      clearTimeout(id);
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", follow);
      window.removeEventListener("scroll", follow, { capture: true });
    };
  }, [cur, name, step, set]);

  useEffect(() => {
    if (!cur) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") finish(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!name) return null;
  function finish() {
    const done = new Set(me?.preferences.learning.tours_done ?? []);
    done.add(name!);
    update.mutate({ learning: { tours_done: [...done].slice(-20) } });
    set(null);
  }
  if (!cur) {
    finish();
    return null;
  }
  const last = step === steps.length - 1;
  const box = cur.sel ? rect : null; // a step without a target is a centred card
  const pad = 6;
  const cardTop = box ? (box.bottom + 180 < window.innerHeight ? box.bottom + 14 : Math.max(12, box.top - 190)) : undefined;
  const cardLeft = box ? Math.min(Math.max(12, box.left), window.innerWidth - 340) : undefined;
  return (
    <div className="fixed inset-0 z-[100]" role="dialog" aria-modal="true" aria-label={t("tour.label")}
      onPointerDown={(e) => {
        // A click on the dimmed page (not the card) ends the tour and goes through to what was clicked, so a new user
        // who taps the "Ask Aasan" box or a button isn't silently blocked by the tour (seen with new sign-ups).
        if (card.current?.contains(e.target as Node)) return;
        e.preventDefault();
        const { clientX: x, clientY: y } = e;
        finish();
        requestAnimationFrame(() => {
          const el = document.elementFromPoint(x, y) as HTMLElement | null;
          el?.focus?.();
          el?.click?.();
        });
      }}>
      {box ? (
        <div className="pointer-events-none absolute rounded-xl ring-4 ring-accent transition-[width,height] duration-300"
          style={{ top: box.top - pad, left: box.left - pad, width: box.width + pad * 2, height: box.height + pad * 2, boxShadow: "0 0 0 9999px rgba(20,14,8,.55)" }} />
      ) : <div className="absolute inset-0 bg-[rgba(20,14,8,.55)]" />}
      <div ref={card} className="absolute w-[320px] max-w-[calc(100vw-24px)] rounded-2xl border-2 border-accent bg-surface p-4 shadow-2xl"
        style={box ? { top: cardTop, left: cardLeft } : { top: "50%", left: "50%", transform: "translate(-50%,-50%)" }}>
        <div className="flex gap-3">
          <Kili mood={step === 0 ? "wave" : last ? "celebrate" : "talking"} size={56} />
          <div className="min-w-0">
            <p className="font-display font-bold">{t(`tour.${cur.key}.title`, { name: me?.preferences.mascot.name ?? "Kili" })}</p>
            <p className="text-sm text-muted">{t(`tour.${cur.key}.body`)}</p>
          </div>
        </div>
        <div className="mt-3 flex items-center gap-2">
          <span className="text-xs text-muted">{step + 1} / {steps.length}</span>
          <button className="ml-auto text-sm text-muted hover:text-ink" onClick={finish}>{t("tour.skip")}</button>
          {step > 0 && <Button variant="ghost" className="py-1 text-sm" onClick={() => set(name, step - 1)}>{t("common.back")}</Button>}
          <Button className="py-1 text-sm" autoFocus onClick={() => (last ? finish() : set(name, step + 1))}>{last ? t("tour.done") : t("onboarding.next")}</Button>
        </div>
      </div>
    </div>
  );
}
