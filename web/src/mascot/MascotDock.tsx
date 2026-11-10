import { AnimatePresence, motion } from "motion/react";
import { COMPANION_EMOJI } from "./name";
import { Minus, MessageCircleHeart } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { cn } from "@/lib/cn";
import type { Preferences } from "@/lib/types";

import { Kili } from "./Kili";
import { useMascot } from "./store";

const SLEEP_AFTER_MS = 90_000;

/** Always-on companion: floats over every page and reacts to the learner. */
export function MascotDock({ prefs }: { prefs: Preferences["mascot"] }) {
  const { mood, bubble, minimized, mouth, react, say, hush, setMinimized } = useMascot();
  const [look, setLook] = useState<{ x: number; y: number } | null>(null);
  const lastActive = useRef(0);
  const navigate = useNavigate();
  const { t } = useTranslation();
  const constraints = useRef<HTMLDivElement>(null);

  // Eyes follow pointer; inactivity → sleepy; typing → watching.
  useEffect(() => {
    lastActive.current = Date.now();
    let raf = 0;
    const wake = () => {
      lastActive.current = Date.now();
      if (useMascot.getState().mood === "sleepy") react("wave");
    };
    const onMove = (e: PointerEvent) => {
      wake();
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => setLook({ x: e.clientX, y: e.clientY }));
    };
    let typingTimer: ReturnType<typeof setTimeout>;
    const onKey = (e: KeyboardEvent) => {
      wake();
      const target = e.target as HTMLElement;
      if (!target.matches("input, textarea, [contenteditable=true]")) return;
      const r = target.getBoundingClientRect();
      setLook({ x: r.left + Math.min(r.width, 40 + (target as HTMLInputElement).value?.length * 8 || 0), y: r.top + r.height / 2 });
      const m = useMascot.getState().mood;
      if (m === "idle" || m === "watching") {
        react("watching");
        clearTimeout(typingTimer);
        typingTimer = setTimeout(() => useMascot.getState().mood === "watching" && react("idle"), 1500);
      }
    };
    const sleepCheck = setInterval(() => {
      if (Date.now() - lastActive.current > SLEEP_AFTER_MS && useMascot.getState().mood === "idle") react("sleepy");
    }, 5000);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("keydown", onKey);
      clearInterval(sleepCheck);
      clearTimeout(typingTimer);
      cancelAnimationFrame(raf);
    };
  }, [react]);

  if (!prefs.enabled) return null;
  const left = prefs.position === "bottom-left";

  return (
    <div ref={constraints} className="pointer-events-none fixed inset-3 z-50">
      <motion.div
        drag
        dragConstraints={constraints}
        dragMomentum={false}
        className={cn("pointer-events-auto absolute bottom-0 flex flex-col items-end gap-2", left ? "left-0 items-start" : "right-0")}
        data-testid="mascot-dock"
        data-mood={mood}
      >
        <AnimatePresence>
          {bubble && !minimized && (
            <motion.div
              key={bubble.id}
              initial={{ opacity: 0, y: 10, scale: 0.9 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 6, scale: 0.95 }}
              className="relative max-w-64 rounded-2xl border border-line bg-surface px-4 py-3 text-sm shadow-lg"
              role="status"
              aria-live="polite"
            >
              <p className="whitespace-pre-line">{bubble.text}</p>
              {bubble.actions && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {bubble.actions.map((a) => (
                    <button
                      key={a.label}
                      onClick={() => {
                        hush();
                        a.onClick();
                      }}
                      className="rounded-full bg-accent px-3 py-1 text-xs font-semibold text-accent-ink"
                    >
                      {a.label}
                    </button>
                  ))}
                </div>
              )}
              <span className={cn("absolute -bottom-2 h-4 w-4 rotate-45 border-b border-r border-line bg-surface", left ? "left-8" : "right-10")} />
            </motion.div>
          )}
        </AnimatePresence>

        <div className="group relative">
          {minimized ? (
            <button
              onClick={() => setMinimized(false)}
              className="flex h-14 w-14 items-center justify-center rounded-full border-2 border-accent bg-surface shadow-lg"
              aria-label={t("mascot.expand", { name: prefs.name })}
            >
              <Kili mood={mood} color={prefs.color} size={48} lookAt={look} />
            </button>
          ) : (
            <>
              <button
                onDoubleClick={() => navigate("/mentor")}
                onClick={() => {
                  react("wave");
                  say(t("mascot.poke", { name: prefs.name, emoji: COMPANION_EMOJI[prefs.character] ?? "🦜" }), {
                    actions: [{ label: t("mascot.openMentor"), onClick: () => navigate("/mentor") }],
                  });
                }}
                className="cursor-grab rounded-full active:cursor-grabbing"
                aria-label={t("mascot.label", { name: prefs.name })}
              >
                <Kili mood={mood} color={prefs.color} accessories={prefs.accessories} outfit={prefs.outfit} size={112} lookAt={look} mouth={mouth} />
              </button>
              <div className="absolute -top-1 right-0 flex gap-1 opacity-0 transition group-hover:opacity-100 group-focus-within:opacity-100">
                <button onClick={() => navigate("/mentor")} className="rounded-full bg-surface p-1 shadow" aria-label={t("mascot.openMentor")}>
                  <MessageCircleHeart className="h-4 w-4 text-accent" />
                </button>
                <button onClick={() => setMinimized(true)} className="rounded-full bg-surface p-1 shadow" aria-label={t("mascot.minimize")}>
                  <Minus className="h-4 w-4" />
                </button>
              </div>
            </>
          )}
        </div>
      </motion.div>
    </div>
  );
}
