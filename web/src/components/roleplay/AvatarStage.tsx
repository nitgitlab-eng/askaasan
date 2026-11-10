import { Box, MessageSquare } from "lucide-react";
import { Component, lazy, Suspense, useCallback, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Md } from "@/components/Md";
import { cn } from "@/lib/cn";
import type { Scenario } from "@/lib/roleplay";
import type { ChatMsg } from "@/lib/useMentorSocket";
import { useMe } from "@/lib/useMe";
import { useMascot } from "@/mascot/store";
import type { VoiceState } from "@/voice/useVoiceMode";

import { avatarLook, inferEmotion } from "./avatarLook";

// three.js is only downloaded when the 3D view is actually opened.
const Avatar3D = lazy(() => import("./Avatar3D"));

type View = "chat" | "3d";
const VIEW_KEY = "aasan.roleplay.view";

function readView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === "3d" ? "3d" : "chat";
  } catch {
    return "chat";
  }
}

let webglOk: boolean | undefined;
function hasWebGL() {
  if (webglOk !== undefined) return webglOk;
  try {
    const c = document.createElement("canvas");
    const gl = (c.getContext("webgl2") ?? c.getContext("webgl")) as WebGLRenderingContext | null;
    webglOk = !!gl;
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
  } catch {
    webglOk = false;
  }
  return webglOk;
}

class Boundary extends Component<{ onError: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onError();
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

interface Props {
  scenario: Scenario;
  messages: ChatMsg[];
  busy: boolean;
  voiceState?: VoiceState;
  /** Live speech-to-text preview while the learner talks. */
  interim?: string;
  /** The chat transcript; stays visible in both views. */
  children: ReactNode;
}

/** Chat ⇄ 3D toggle for role-play. In 3D the character is an animated avatar with captions; the transcript stays alongside. */
export function AvatarStage({ scenario, messages, busy, voiceState = "off", interim, children }: Props) {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const [view, setView] = useState<View>(readView);
  const [failed, setFailed] = useState(false);
  const supported = useMemo(() => view === "3d" && hasWebGL(), [view]);
  const show3d = view === "3d" && supported && !failed;

  const choose = (v: View) => {
    setView(v);
    if (v === "3d") setFailed(false);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* private mode — choice just isn't remembered */
    }
  };

  const reducedMotion =
    !!me?.preferences.appearance.reduced_motion ||
    (typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

  const look = useMemo(
    () => avatarLook({ name: scenario.character.name, persona: scenario.character.persona, title: scenario.title }),
    [scenario.character.name, scenario.character.persona, scenario.title],
  );

  const last = messages[messages.length - 1];
  const lastReply = [...messages].reverse().find((m) => m.role === "assistant");
  const voiceOn = voiceState !== "off";
  const waiting =
    (busy && (!last || last.role === "user" || (last.streaming && !last.content))) || voiceState === "thinking" || voiceState === "transcribing";
  const speaking = voiceOn ? voiceState === "speaking" : !!(last?.role === "assistant" && last.streaming && last.content);
  const emotion = inferEmotion(lastReply?.content, { waiting });
  const getLevel = useCallback(() => useMascot.getState().mouth, []);
  const onError = useCallback(() => setFailed(true), []);

  const note = view === "3d" && !supported ? t("avatar3d.noWebgl") : view === "3d" && failed ? t("avatar3d.failed") : null;
  const state = waiting ? t("avatar3d.mood.thinking") : speaking ? t("avatar3d.speaking") : t(`avatar3d.mood.${emotion}`);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-2 flex items-center justify-end gap-2">
        <div role="group" aria-label={t("avatar3d.viewLabel")} className="inline-flex rounded-full bg-surface-2 p-0.5 text-xs font-semibold">
          {(["chat", "3d"] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => choose(v)}
              aria-pressed={view === v}
              className={cn("flex items-center gap-1 rounded-full px-3 py-1.5", view === v ? "bg-accent text-accent-ink" : "text-muted hover:text-ink")}
            >
              {v === "chat" ? <MessageSquare className="h-3.5 w-3.5" /> : <Box className="h-3.5 w-3.5" />}
              {v === "chat" ? t("avatar3d.chat") : t("avatar3d.view3d")}
            </button>
          ))}
        </div>
      </div>
      {note && (
        <p role="status" className="mb-2 rounded-xl bg-surface-2 px-3 py-2 text-xs text-muted">
          {note}
        </p>
      )}
      <div className="flex min-h-0 flex-1 flex-col gap-3 md:flex-row">
        {show3d && (
          <figure className="flex max-h-[58%] shrink-0 flex-col overflow-hidden rounded-2xl border border-line bg-surface md:max-h-none md:w-1/2">
            <div role="img" aria-label={t("avatar3d.avatarLabel", { name: scenario.character.name, state })} className="relative h-[30dvh] min-h-20 shrink md:h-auto md:min-h-0 md:flex-1">
              <Boundary onError={onError}>
                <Suspense fallback={<p className="absolute inset-0 flex items-center justify-center text-sm text-muted">{t("avatar3d.loading")}</p>}>
                  <Avatar3D className="absolute inset-0" look={look} emotion={emotion} speaking={speaking} getLevel={getLevel} reducedMotion={reducedMotion} onError={onError} />
                </Suspense>
              </Boundary>
              <span className="absolute left-2 top-2 rounded-full bg-surface/85 px-2 py-0.5 text-[11px] font-semibold text-muted">{state}</span>
            </div>
            <figcaption className="max-h-16 shrink-0 overflow-y-auto md:max-h-24 border-t border-line px-3 py-2 text-sm" aria-label={t("avatar3d.captions")}>
              <b>{scenario.character.name}:</b>{" "}
              {lastReply?.content ? <div className="prose-chat inline [&_p]:inline"><Md ai>{lastReply.content}</Md></div> : "…"}
              {interim && <span className="mt-1 block text-xs italic text-muted">{t("avatar3d.youSaying")}: {interim}</span>}
            </figcaption>
          </figure>
        )}
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      </div>
    </div>
  );
}
