import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { mascot } from "@/mascot/store";

import { api } from "./api";

/** Once per session, Kili mentions what's worth doing (reviews due, streak at risk…). */
export function useNudges(enabled: boolean, chattiness: number) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const done = useRef(false);
  useEffect(() => {
    if (!enabled || done.current || chattiness < 1) return;
    done.current = true;
    try {
      if (sessionStorage.getItem("aasan-nudged")) return;
      sessionStorage.setItem("aasan-nudged", "1");
    } catch {
      /* storage blocked: still nudge once per mount */
    }
    const timer = setTimeout(async () => {
      const list = await api<{ text: string; link: string }[]>("/api/game/nudges/").catch(() => []);
      const n = list[0];
      if (n) {
        mascot.react("wave");
        mascot.say(n.text, { ms: 9000, actions: [{ label: t("game.letsGo"), onClick: () => navigate(n.link) }] });
      }
    }, 4500);
    return () => clearTimeout(timer);
  }, [enabled, chattiness, navigate, t]);
}
