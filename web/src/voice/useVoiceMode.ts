import { useCallback, useEffect, useRef, useState } from "react";

import type { ChatMsg } from "@/lib/useMentorSocket";
import { mascot, useMascot } from "@/mascot/store";

import {
  BrowserRecognition,
  browserSpeaker,
  fetchVoiceConfig,
  serverSpeaker,
  serverTranscribe,
  startClip,
  type Lang,
  type Speaker,
  type SpeechRecognitionLike,
  type VoiceConfig,
  BCP47,
  unlockAudio,
} from "./engines";
import { decideBargeIn, isEcho, stripWake } from "./bargeIn";
import { type FillerKind, pickFiller, THINK_FILLER_MS } from "./fillers";
import { joinLiveCall, type LiveCall, type LiveFeature } from "./livekit";
import { FATAL_STREAM_ERRORS, openVoiceStream, type StreamEvent, type VoiceStream } from "./stream";
import { SentenceStream } from "./text";
import { startMicVad, type MicVad } from "./vad";

/** Voice errors with their own message under mentor.voice.errors.*; anything else shows "generic". */
export const VOICE_ERRORS = ["mic_denied", "browser_stt_unsupported", "voice_budget_exceeded", "provider_not_configured", "stt_no_words", "stt_network", "mic_busy", "stt_language", "plan_limit", "stream_closed", "session_limit", "guardian_consent_required"];

/** "ready": voice is on with the mic closed (tap-to-talk, waiting for a tap). */
export type VoiceState = "off" | "starting" | "ready" | "listening" | "hearing" | "transcribing" | "thinking" | "speaking";

/**
 * - `tap`: the mic opens only on `listen()`. Finals from one tap are joined and sent once when the learner falls
 *   silent, then the mic closes. Only `interrupt()` (a deliberate tap) stops the reply.
 * - `handsfree`: the mic stays open, but listening is paused while the reply streams or is spoken, so the reply's own
 *   echo can never be sent as the learner's words. One message per utterance; voice never interrupts.
 *   When the server can stream listening (`stt.streaming`, Deepgram), hands-free becomes **live conversation**
 *   instead: the mic streams the whole time, including while Aasan speaks, and the learner interrupts just by talking
 *   (2+ words that are not Aasan's own echo) or by saying "Aasan" / "stop" / "wait" / நிறுத்து.
 * - `conversation` (default: Ask Aasan's voice screen, Live Class, role-play, hands-free workshops): a back-and-forth
 *   like a phone call. Streamed listening when the server
 *   has it (same as live conversation above). Otherwise it is on the browser recogniser, whose mic has no reliable
 *   echo cancelling: listening pauses while Aasan talks (a tap interrupts it) and resumes the moment it stops, and the
 *   turn is sent the moment the learner pauses (no waiting for the recogniser to wrap up). Either way, Aasan's own
 *   last words heard just after it stops are dropped (the echo tail).
 */
export type VoiceMode = "tap" | "handsfree" | "conversation";

/** Voice diagnostics: `?voicedebug=1` on the page's own URL keeps a log of what the mic and the browser recogniser
 * did, shown on the Ask Aasan page and in the console, so a failure can be pinned down. Never sticky: learners must
 * not keep seeing it after one debugging session. */
export const voiceDebug = (() => {
  let on = false;
  try {
    on = new URLSearchParams(location.search).get("voicedebug") === "1";
    localStorage.removeItem("aasan-voice-debug"); // older builds remembered the flag
  } catch {
    /* storage blocked */
  }
  const lines: string[] = [];
  const subs = new Set<() => void>();
  const t0 = typeof performance !== "undefined" ? performance.now() : 0;
  return {
    get on() {
      return on;
    },
    lines,
    subscribe(fn: () => void) {
      subs.add(fn);
      return () => void subs.delete(fn);
    },
    log(msg: string) {
      if (!on) return;
      lines.push(`${Math.round(performance.now() - t0)}ms ${msg}`);
      if (lines.length > 80) lines.shift();
      console.debug("[aasan-voice]", msg);
      subs.forEach((f) => f());
    },
  };
})();

interface Opts {
  messages: ChatMsg[];
  send: (text: string) => boolean;
  cancel: () => void;
  /** Preferred recognition language for browser STT. */
  lang: Lang;
  mode?: VoiceMode;
  /** Read replies aloud (default true). Off: voice only listens; replies stay on screen. */
  speak?: boolean;
  /** What is said instead of reading a code block. */
  codeCue?: string;
  /** The chat is still busy with a reply (live conversation holds the next turn until it is free). */
  busy?: boolean;
  /** Which screen this is, for a live voice call (LiveKit) when the server has one. */
  feature?: LiveFeature;
  /** What the reply is doing before its first word: "searching" while the server looks something up on the web. */
  activity?: "searching" | null;
  /** Spoken fillers while waiting ("all" default; "think" for role-play and workshops; "none"). */
  fillers?: FillerKind;
}

const ECHO_GUARD = 2.5; // raise VAD threshold while Aasan is talking
/** Turn modes: give up waiting for the recogniser's words this long after the utterance ended. */
const STUCK_MS = 4000;
/** Turn modes: send what was heard if recognition goes quiet this long without the VAD noticing the end. */
export const RESULT_SILENCE_MS = 2000;
/** Tap-to-talk: close the mic if nothing is said this long after the tap. */
export const NO_SPEECH_MS = 10_000;
/** Conversation: the pause that ends the learner's turn, and the recogniser-quiet fallback when the VAD misses it. */
export const TURN_PAUSE_MS = 700;
export const TURN_SILENCE_MS = 1200;
/** After Aasan stops, words that echo what it said are still its own voice arriving late, for this long. */
export const ECHO_TAIL_MS = 1500;
/** Conversation on the browser recogniser: listening resumes this soon after Aasan stops (room echo dies away). */
export const RESUME_AFTER_MS = 300;
/** How many of Aasan's recent sentences the echo check compares against (about this reply and the one before). */
const SPOKEN_KEPT = 30;

/** Hands-free, interruptible voice conversation layered on the mentor chat. */
export function useVoiceMode({ messages, send, cancel, lang, mode = "conversation", speak = true, codeCue, busy = false, feature = "mentor", activity = null, fillers = "all" }: Opts) {
  const [state, setState] = useState<VoiceState>("off");
  const [error, setError] = useState<string | null>(null);
  const [interim, setInterim] = useState("");
  /** The sentence being spoken right now (live captions); "" when quiet. */
  const [saying, setSaying] = useState("");
  const speakRef = useRef(speak);
  const cueRef = useRef(codeCue);
  useEffect(() => {
    cueRef.current = codeCue;
  }, [codeCue]);
  const vad = useRef<MicVad | null>(null);
  const speaker = useRef<Speaker | null>(null);
  const recog = useRef<SpeechRecognitionLike | null>(null);
  const clip = useRef<ReturnType<typeof startClip> | null>(null);
  const config = useRef<VoiceConfig | null>(null);
  const stream = useRef<{ id: ChatMsg["id"] | null; splitter: SentenceStream }>({ id: null, splitter: new SentenceStream() });
  const on = state !== "off";
  const sendRef = useRef(send);
  useEffect(() => {
    sendRef.current = send;
  }, [send]);
  const modeRef = useRef(mode);
  const langRef = useRef(lang);
  useEffect(() => {
    langRef.current = lang;
  }, [lang]);

  // Turn-mode bookkeeping.
  const heard = useRef(""); // finals of the current utterance
  const partial = useRef(""); // latest interim of the current utterance
  const ending = useRef(false); // recognition was asked to stop to flush the utterance
  const paused = useRef(false); // hands-free: the host is talking, so listening is paused
  const micOpen = useRef(false);
  const streaming = useRef(false); // the last message is a streaming reply
  const muted = useRef<ChatMsg["id"] | null>(null); // a reply the learner interrupted: don't speak the rest of it
  const silenceTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const noSpeechTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const stuckTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // Each mic opening gets a number; a slower, older opening that finishes late must not create a second recogniser
  // (seen live: switching hands-free on opened the mic twice, and the words went to an orphan recogniser).
  const openGen = useRef(0);
  const closeMicRef = useRef<() => void>(() => {});

  // Live conversation (streamed listening).
  const [streamOk, setStreamOk] = useState(false); // the server can stream listening (and it hasn't failed)
  const liveStream = useRef<VoiceStream | null>(null);
  const liveHeard = useRef(""); // finals of the learner's current turn
  const livePartial = useRef(""); // latest interim after them
  const bargedIn = useRef(false); // this turn already cut Aasan off
  const pendingTurn = useRef<string | null>(null); // a turn said while the cut-off reply is still winding down
  const sayingRef = useRef("");
  const recentSpoken = useRef<string[]>([]); // the last sentences Aasan spoke (echo check)
  const hostStoppedAt = useRef(-Infinity); // when Aasan last went quiet (echo tail)
  const resumeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // Latency diagnostics (?voicedebug=1): when the last turn went out, and whether its first word / sound has arrived.
  const turnAt = useRef(0);
  const firstToken = useRef(false);
  const firstAudio = useRef(false);
  const busyRef = useRef(busy);
  // One spoken filler per turn ("one moment, let me look that up"), so the call never goes silent while Aasan works.
  const fillersRef = useRef(fillers);
  useEffect(() => {
    fillersRef.current = fillers;
  }, [fillers]);
  const fillerSaid = useRef(false);
  const awaitingReply = useRef(false); // a turn went out and no word of its reply has arrived yet
  const fillerOpen = useRef(false); // a filler went out and no reply sentence has followed it yet
  const fillerTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const stopRef = useRef<() => void>(() => {});
  // A live voice call (LiveKit): listening and speaking both go through it.
  const call = useRef<LiveCall | null>(null);
  const featureRef = useRef(feature);
  const isLive = useCallback(
    () => (modeRef.current === "handsfree" || modeRef.current === "conversation") && (!!call.current || !!config.current?.stt.streaming),
    [],
  );
  const spokenNow = useCallback(() => [sayingRef.current, ...recentSpoken.current].filter(Boolean), []);
  /** Just after Aasan stopped, and the words are its own: the recogniser finishing Aasan's last sentence late. */
  const echoTail = useCallback(
    (text: string) => performance.now() - hostStoppedAt.current < ECHO_TAIL_MS && isEcho(text, spokenNow()),
    [spokenNow],
  );

  // Conversation on the browser recogniser. Chrome keeps every result of a session in one list; turns already sent
  // and Aasan's own echo sit before `resultBase`, so only what came after counts as the learner's words.
  const resultBase = useRef(0);
  const resultCount = useRef(0);
  const [micMuted, setMicMuted] = useState(false);
  const micMutedRef = useRef(false);

  const messagesRef = useRef(messages);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const setMood = useMascot((s) => s.react);
  const idle = useCallback((): VoiceState => (modeRef.current === "tap" ? "ready" : "listening"), []);

  /** Stop speaking locally (the server stops the reply itself when it gets the learner's next message). */
  const hush = useCallback(() => {
    clearTimeout(fillerTimer.current);
    awaitingReply.current = false;
    if (speaker.current?.busy) hostStoppedAt.current = performance.now();
    speaker.current?.cancel();
    const last = messagesRef.current[messagesRef.current.length - 1];
    if (last?.role === "assistant" && last.streaming) muted.current = last.id;
    useMascot.setState({ mouth: null });
    setSaying("");
  }, []);

  /** A deliberate interruption (mascot or Stop tap, or live barge-in): stop speaking and stop the reply on the server. */
  const interrupt = useCallback(() => {
    const last = messagesRef.current[messagesRef.current.length - 1];
    const talking = !!speaker.current?.busy || streaming.current || (busyRef.current && last?.role === "user");
    hush();
    if (talking) cancel();
    setState((s) => (s === "speaking" || s === "thinking" ? idle() : s));
  }, [cancel, hush, idle]);
  const interruptRef = useRef(interrupt);
  useEffect(() => {
    interruptRef.current = interrupt;
  }, [interrupt]);

  /** Say one filler for this turn, only while no word of the reply has arrived (never saved into the reply). */
  const sayFiller = useCallback((kind: "search" | "think") => {
    const spk = speaker.current;
    const allowed = fillersRef.current === "all" || (fillersRef.current === "think" && kind === "think");
    if (!spk || !allowed || !speakRef.current || fillerSaid.current || !awaitingReply.current) return;
    fillerSaid.current = true;
    fillerOpen.current = true;
    const line = pickFiller(langRef.current, kind);
    voiceDebug.log(`filler (${kind}): ${line}`);
    spk.speak(line);
  }, []);

  const submit = useCallback((text: string) => {
    const t = text.trim();
    setInterim("");
    if (!t) {
      setState(idle());
      return;
    }
    setState("thinking");
    turnAt.current = performance.now();
    firstToken.current = false;
    firstAudio.current = false;
    fillerSaid.current = false;
    clearTimeout(fillerTimer.current);
    if (!sendRef.current(t)) {
      setState(idle());
      return;
    }
    awaitingReply.current = true;
    fillerTimer.current = setTimeout(() => sayFiller("think"), THINK_FILLER_MS);
  }, [idle, sayFiller]);

  // The server is searching the web: say so (instead of the thinking line, if that hasn't been said yet).
  useEffect(() => {
    if (activity !== "searching" || fillersRef.current !== "all") return; // else the thinking line still comes
    clearTimeout(fillerTimer.current);
    sayFiller("search");
  }, [activity, sayFiller]);

  /** Closes the mic (VAD, clip, recognition) without touching the speaker. */
  const closeMic = useCallback(() => {
    openGen.current++;
    micOpen.current = false;
    clearTimeout(stuckTimer.current);
    clearTimeout(silenceTimer.current);
    clearTimeout(noSpeechTimer.current);
    clearTimeout(resumeTimer.current);
    vad.current?.stop();
    vad.current = null;
    clip.current?.discard();
    clip.current = null;
    const r = recog.current;
    recog.current = null; // before abort, so its onend doesn't restart it
    r?.abort();
    heard.current = "";
    partial.current = "";
    ending.current = false;
    liveStream.current?.stop();
    liveStream.current = null;
    liveHeard.current = "";
    livePartial.current = "";
    bargedIn.current = false;
  }, []);

  useEffect(() => {
    closeMicRef.current = closeMic;
  }, [closeMic]);

  /** Live: Aasan is talking (speaking, streaming a reply that wasn't cut off, or about to answer). */
  const hostBusy = useCallback(() => {
    const last = messagesRef.current[messagesRef.current.length - 1];
    if (speaker.current?.busy) return true;
    if (streaming.current && last?.id !== muted.current) return true;
    return busyRef.current && last?.role === "user"; // waiting for the reply to start
  }, []);

  /** Live: the learner's turn is over (speech_final / utterance_end / a tap): send it as one message. */
  const endLiveTurn = useCallback(() => {
    const text = stripWake(`${liveHeard.current} ${livePartial.current}`.trim());
    liveHeard.current = "";
    livePartial.current = "";
    bargedIn.current = false;
    setInterim("");
    if (!text) {
      setState((s) => (s === "hearing" ? "listening" : s));
      return;
    }
    voiceDebug.log(`live turn: ${JSON.stringify(text)}`);
    if (busyRef.current) {
      // The reply that was cut off is still winding down on the server: send as soon as it has.
      pendingTurn.current = text;
      setState("thinking");
      return;
    }
    submit(text);
  }, [submit]);

  /** Conversation (browser recogniser): the learner paused, so send what was heard now. The recogniser keeps running;
   * this turn's results (and any late final for them) are skipped from here on. */
  const sendTurn = useCallback(() => {
    clearTimeout(silenceTimer.current);
    const text = stripWake(`${heard.current} ${partial.current}`.trim());
    heard.current = "";
    partial.current = "";
    resultBase.current = resultCount.current;
    const cutIn = bargedIn.current;
    bargedIn.current = false;
    setInterim("");
    if (!text) {
      setState((s) => (s === "hearing" ? "listening" : s));
      return;
    }
    voiceDebug.log(`turn: ${JSON.stringify(text)}${cutIn ? " (cut in)" : ""}`);
    if (busyRef.current) {
      pendingTurn.current = text; // the reply that was cut off is still winding down
      setState("thinking");
      return;
    }
    submit(text);
  }, [submit]);

  const liveEvent = useCallback((ev: StreamEvent) => {
    if (ev.type === "error") {
      setError(ev.code);
      if (FATAL_STREAM_ERRORS.has(ev.code) || ev.code === "stream_closed") stopRef.current();
      return;
    }
    if (ev.type === "speech_started") {
      voiceDebug.log("stream speech_started");
      return;
    }
    if (ev.type === "utterance_end") {
      voiceDebug.log("stream utterance_end");
      endLiveTurn();
      return;
    }
    if (ev.type !== "interim" && ev.type !== "final") return;
    const text = ev.text.trim();
    const speechFinal = ev.type === "final" && ev.speech_final;
    voiceDebug.log(`stream ${ev.type}${speechFinal ? " (speech_final)" : ""}: ${JSON.stringify(text)}`);
    let accept = !!text;
    if (text && call.current) {
      // A real call: the browser's echo cancelling already removed Aasan's voice from the mic, and the agent stops
      // speaking by itself when the learner talks. Every word heard is the learner's.
      if (!bargedIn.current && hostBusy()) {
        bargedIn.current = true;
        interruptRef.current();
      }
    } else if (text && !bargedIn.current && hostBusy()) {
      const heardSoFar = `${liveHeard.current} ${text}`.trim();
      const decision = decideBargeIn(heardSoFar, spokenNow());
      voiceDebug.log(`barge-in ${JSON.stringify(heardSoFar)} → ${decision ?? "ignored (echo or too short)"}`);
      if (decision) {
        bargedIn.current = true;
        interruptRef.current();
      } else accept = false;
    } else if (text && !bargedIn.current && !liveHeard.current && echoTail(text)) {
      voiceDebug.log(`ignored ${JSON.stringify(text)}: Aasan's own last words, heard late`);
      accept = false;
    }
    if (accept) {
      if (ev.type === "final") {
        liveHeard.current = `${liveHeard.current} ${text}`.trim();
        livePartial.current = "";
      } else livePartial.current = text;
      const shown = stripWake(`${liveHeard.current} ${livePartial.current}`.trim());
      setInterim(shown);
      if (shown) {
        setError((x) => (x === "stt_no_words" ? null : x));
        setState("hearing");
        mascot.react("watching", 0);
      }
    }
    if (speechFinal) endLiveTurn();
  }, [echoTail, endLiveTurn, hostBusy, spokenNow]);

  const stop = useCallback(() => {
    clearTimeout(fillerTimer.current);
    awaitingReply.current = false;
    fillerOpen.current = false;
    closeMic();
    micMutedRef.current = false;
    setMicMuted(false);
    pendingTurn.current = null;
    speaker.current?.cancel();
    speaker.current?.dispose?.();
    speaker.current = null;
    call.current = null;
    useMascot.setState({ mouth: null });
    mascot.react("idle");
    setInterim("");
    setSaying("");
    setState("off");
  }, [closeMic]);

  /** Turn modes: ask recognition to stop so the pending words arrive as finals, then onend sends them once. */
  const endUtterance = useCallback(() => {
    clearTimeout(silenceTimer.current);
    const r = recog.current;
    if (!r || ending.current) return;
    ending.current = true;
    voiceDebug.log("utterance ended: asking the recogniser for its words");
    r.stop();
    // Safety net: if the recogniser never answers (no "end" at all), reset instead of hanging on "Hearing you…".
    clearTimeout(stuckTimer.current);
    stuckTimer.current = setTimeout(() => {
      if (recog.current !== r || !ending.current) return;
      voiceDebug.log("recogniser gave no answer in 4 s: resetting");
      ending.current = false;
      heard.current = "";
      partial.current = "";
      setInterim("");
      setError("stt_no_words");
      if (modeRef.current === "tap") {
        closeMicRef.current();
        setState((st) => (st === "off" ? st : "ready"));
      } else {
        setState((st) => (st === "hearing" ? "listening" : st));
        try {
          r.abort();
        } catch {
          /* already stopped; onend restarts it */
        }
      }
      mascot.react("idle");
    }, STUCK_MS);
  }, []);

  const openMic = useCallback(async () => {
    let cfg = config.current;
    if (!cfg || micOpen.current || micMutedRef.current) return;
    const m = modeRef.current;
    if (isLive()) {
      micOpen.current = true;
      const gen = ++openGen.current;
      voiceDebug.log(`live stream opening #${gen} (${langRef.current}${call.current ? ", live call" : ""})`);
      try {
        const s = call.current ? await call.current.listen(liveEvent) : await openVoiceStream(langRef.current, liveEvent, voiceDebug.log);
        if (!micOpen.current || gen !== openGen.current) {
          voiceDebug.log("stale stream opening discarded");
          s.stop();
          return;
        }
        liveStream.current = s;
        return;
      } catch (e) {
        micOpen.current = false;
        const err = e as Error;
        // A blocked mic or a used-up allowance is the learner's to fix; anything else falls back to hands-free.
        if (err.name === "NotAllowedError" || ["plan_limit", "voice_budget_exceeded", "unauthorized", "feature_off", "guardian_consent_required"].includes(err.message)) throw e;
        voiceDebug.log(`live stream unavailable (${err.message}): using hands-free instead`);
        cfg = { ...cfg, stt: { ...cfg.stt, streaming: false } };
        config.current = cfg;
        setStreamOk(false);
        micOpen.current = false;
      }
    }
    const useBrowserStt = cfg.stt.engine === "browser";
    if (useBrowserStt && !BrowserRecognition) throw new Error("browser_stt_unsupported");
    micOpen.current = true;
    const gen = ++openGen.current;
    voiceDebug.log(`mic opening #${gen} (mode ${m})`);
    heard.current = "";
    partial.current = "";
    ending.current = false;

    const transcribeClip = (c: NonNullable<typeof clip.current>) => {
      setState("transcribing");
      mascot.react("thinking", 0);
      void c
        .stop()
        .then(({ blob, seconds }) => serverTranscribe(blob, seconds))
        .then(submit)
        .catch((e: Error & { code?: string }) => {
          setError(e.code ?? "stt_failed");
          setState(idle());
          mascot.react("confused");
        });
    };

    // Conversation on the browser recogniser: its mic has no reliable echo cancelling, so listening pauses while
    // Aasan talks (a tap interrupts) and each turn is sent the moment the learner pauses.
    const quickTurns = m === "conversation" && useBrowserStt;
    const v = await startMicVad((ev) => {
      if (quickTurns) {
        voiceDebug.log(`vad ${ev}${paused.current ? " (ignored: Aasan is talking)" : ""}`);
        if (paused.current) return;
        if (ev === "speech-start") {
          setState((s) => (s === "listening" ? "hearing" : s));
          mascot.react("watching", 0);
        } else if (ev === "speech-cancel" && !heard.current && !partial.current) {
          setState((s) => (s === "hearing" ? "listening" : s));
        } else if (ev === "speech-end") {
          if (heard.current || partial.current) sendTurn();
          else {
            // Words may still be on their way from the recogniser; if none come, it was only noise.
            clearTimeout(silenceTimer.current);
            silenceTimer.current = setTimeout(() => {
              if (heard.current || partial.current) sendTurn();
              else setState((s) => (s === "hearing" ? "listening" : s));
            }, TURN_SILENCE_MS);
          }
        }
        return;
      }
      // Turn modes: nothing heard while the host talks counts, and the voice never interrupts.
      voiceDebug.log(`vad ${ev}${paused.current ? " (ignored: paused)" : ""}`);
      if (paused.current) return;
      if (ev === "speech-start") {
        clearTimeout(noSpeechTimer.current);
        setState("hearing");
        mascot.react("watching", 0);
        if (!useBrowserStt && vad.current) clip.current = startClip(vad.current.stream);
      } else if (ev === "speech-cancel") {
        clip.current?.discard();
        clip.current = null;
        setState((s) => (s === "hearing" ? "listening" : s));
        mascot.react("idle");
      } else if (ev === "speech-end") {
        if (!useBrowserStt) {
          const c = clip.current;
          clip.current = null;
          if (m === "tap") closeMic();
          if (c) transcribeClip(c);
        } else endUtterance();
      }
    }, m === "conversation" ? { releaseMs: TURN_PAUSE_MS } : {});
    if (!micOpen.current || gen !== openGen.current) {
      voiceDebug.log("stale mic opening discarded");
      v.stop(); // closed (or re-opened) while the mic was starting
      return;
    }
    vad.current = v;

    if (useBrowserStt && BrowserRecognition) {
      const r = new BrowserRecognition();
      r.lang = BCP47[langRef.current];
      r.continuous = true;
      r.interimResults = true;
      if (quickTurns) {
        r.onresult = (e) => {
          if (recog.current !== r) {
            try {
              r.abort(); // an old recogniser still running
            } catch {
              /* already stopped */
            }
            return;
          }
          resultCount.current = e.results.length;
          if (micMutedRef.current || paused.current) return;
          let fin = "";
          let part = "";
          let afterFinal = resultBase.current;
          for (let i = resultBase.current; i < e.results.length; i++) {
            const res = e.results[i];
            if (res.isFinal) {
              fin = `${fin} ${res[0].transcript}`;
              afterFinal = i + 1;
            } else part = `${part} ${res[0].transcript}`;
          }
          fin = fin.trim();
          part = part.trim();
          const text = `${fin} ${part}`.trim();
          voiceDebug.log(`recognition: ${JSON.stringify(text)}`);
          if (!text) return;
          if (!heard.current && !partial.current && echoTail(text)) {
            voiceDebug.log(`ignored ${JSON.stringify(text)}: Aasan's own last words, heard late`);
            resultBase.current = afterFinal; // finished echo lines never count again
            return;
          }
          heard.current = fin;
          partial.current = part;
          setError((x) => (x === "stt_no_words" ? null : x));
          setInterim(stripWake(text));
          setState("hearing");
          mascot.react("watching", 0);
          // Safety net if the VAD misses the end of the turn (a very quiet mic).
          clearTimeout(silenceTimer.current);
          silenceTimer.current = setTimeout(() => {
            if (!vad.current?.machine.speaking) sendTurn();
          }, TURN_SILENCE_MS);
        };
        r.onend = () => {
          voiceDebug.log("recognition end");
          if (recog.current !== r) return;
          if (heard.current || partial.current) sendTurn();
          if (!micOpen.current || paused.current) return; // paused: resumes when Aasan stops
          try {
            r.start(); // Chrome stopped by itself after silence: keep listening
          } catch {
            /* already running */
          }
        };
      } else {
        r.onresult = (e) => {
          voiceDebug.log(`recognition result${paused.current ? " (ignored: paused)" : ""}${recog.current !== r ? " (orphan: stopped)" : ""}: ${JSON.stringify(e.results[e.results.length - 1]?.[0]?.transcript ?? "")}`);
          if (recog.current !== r) {
            try {
              r.abort(); // an old recogniser still running: stop it so the live one gets the mic
            } catch {
              /* already stopped */
            }
            const live = recog.current;
            if (live && micOpen.current && !paused.current) {
              setTimeout(() => {
                try {
                  live.start();
                } catch {
                  /* already running */
                }
              }, 150);
            }
            return;
          }
          if (paused.current) return;
          setError((x) => (x === "stt_no_words" ? null : x));
          let part = "";
          for (let i = e.resultIndex; i < e.results.length; i++) {
            const res = e.results[i];
            if (res.isFinal) heard.current = `${heard.current} ${res[0].transcript}`.trim();
            else part += res[0].transcript;
          }
          partial.current = part;
          setInterim(`${heard.current} ${part}`.trim());
          clearTimeout(noSpeechTimer.current);
          // Safety net if the VAD misses the end of the utterance (a very quiet mic).
          clearTimeout(silenceTimer.current);
          silenceTimer.current = setTimeout(() => {
            if (!vad.current?.machine.speaking) endUtterance();
          }, RESULT_SILENCE_MS);
        };
        r.onend = () => {
          voiceDebug.log(`recognition end (text: ${JSON.stringify(`${heard.current} ${partial.current}`.trim())})`);
          if (recog.current !== r) return;
          const text = paused.current ? "" : `${heard.current} ${partial.current}`.trim();
          heard.current = "";
          partial.current = "";
          const wasEnding = ending.current;
          ending.current = false;
          clearTimeout(stuckTimer.current);
          clearTimeout(silenceTimer.current);
          if (!text && wasEnding) {
            // Speech ended but the recogniser gave no words: don't sit on "Hearing you…" forever.
            setInterim("");
            setError("stt_no_words");
            if (modeRef.current === "tap") {
              closeMic();
              setState((s) => (s === "off" ? s : "ready"));
              mascot.react("idle");
              return;
            }
            setState((s) => (s === "hearing" ? "listening" : s));
            mascot.react("idle");
          }
          if (text) {
            if (modeRef.current === "tap") closeMic(); // exactly one message per tap
            submit(text);
            if (modeRef.current === "tap") return;
          }
          if (!micOpen.current) return;
          if (modeRef.current === "handsfree" && paused.current) return; // resumes when the host stops talking
          try {
            r.start(); // Chrome stopped by itself after silence: keep listening
          } catch {
            /* already running */
          }
        };
      }
      r.onerror = (e) => {
        voiceDebug.log(`recognition error: ${e.error}`);
        if (e.error === "not-allowed" || e.error === "service-not-allowed") {
          setError("mic_denied");
          stop();
        } else if (e.error === "network") {
          // Chrome sends the audio to its own speech service; without it, nothing comes back.
          setError("stt_network");
        } else if (e.error === "audio-capture") {
          setError("mic_busy");
        } else if (e.error === "language-not-supported") {
          setError("stt_language");
        }
      };
      const origStart = r.start.bind(r);
      r.start = () => {
        voiceDebug.log(`recognition start (lang ${r.lang}, mode ${modeRef.current})`);
        origStart();
        resultBase.current = 0; // a new session starts a new result list
        resultCount.current = 0;
      };
      const prev = recog.current;
      if (prev && prev !== r) {
        recog.current = null; // so its onend doesn't restart it
        try {
          prev.abort();
        } catch {
          /* already stopped */
        }
      }
      recog.current = r;
      if (!((m === "handsfree" || m === "conversation") && paused.current)) r.start();
    }
    if (m === "tap") {
      clearTimeout(noSpeechTimer.current);
      noSpeechTimer.current = setTimeout(() => {
        if (heard.current || partial.current || vad.current?.machine.speaking) return;
        closeMic();
        setInterim("");
        setState((s) => (s === "listening" ? "ready" : s));
        mascot.react("idle");
      }, NO_SPEECH_MS);
    }
  }, [closeMic, echoTail, endUtterance, idle, isLive, liveEvent, sendTurn, stop, submit]);

  /**
   * Hands-free: pause listening while the host talks (reply streaming or being spoken) and resume after.
   * Tap-to-talk: if the host starts speaking while the mic is open, the mic closes.
   */
  const syncPause = useCallback(() => {
    const m = modeRef.current;
    if (!speaker.current) return;
    if (isLive()) {
      paused.current = false; // live conversation never stops listening
      return;
    }
    if (m === "conversation" && config.current?.stt.engine === "browser") {
      const last = messagesRef.current[messagesRef.current.length - 1];
      const talking = !!speaker.current.busy || (streaming.current && last?.id !== muted.current);
      if (talking === paused.current) return;
      paused.current = talking;
      clearTimeout(resumeTimer.current);
      const r = recog.current;
      if (talking) {
        voiceDebug.log("listening paused: Aasan is talking");
        clearTimeout(silenceTimer.current);
        heard.current = "";
        partial.current = "";
        setInterim("");
        setState((s) => (s === "hearing" ? "listening" : s));
        r?.abort();
        return;
      }
      // Aasan is done: listen again once the room is quiet. A new session starts a fresh result list, so nothing
      // the mic caught while Aasan talked can count.
      resumeTimer.current = setTimeout(() => {
        if (paused.current || !micOpen.current || recog.current !== r || !r) return;
        try {
          r.start();
        } catch {
          /* still stopping: its onend restarts it */
        }
      }, RESUME_AFTER_MS);
      return;
    }
    const speaking = !!speaker.current.busy;
    const last = messagesRef.current[messagesRef.current.length - 1];
    const talking = m === "tap" ? speaking : speaking || (streaming.current && last?.id !== muted.current);
    if (talking === paused.current) return;
    paused.current = talking;
    if (m === "tap") {
      if (talking && micOpen.current) {
        closeMic();
        setInterim("");
      }
      return;
    }
    const r = recog.current;
    if (talking) {
      clearTimeout(silenceTimer.current);
      heard.current = "";
      partial.current = "";
      ending.current = false;
      setInterim("");
      clip.current?.discard();
      clip.current = null;
      r?.abort();
    } else if (r) {
      try {
        r.start();
      } catch {
        /* still stopping: its onend restarts it */
      }
    }
  }, [closeMic, isLive]);

  /** `withMode`: start straight into that mode (the caller's `mode` prop catches up on its next render). */
  const start = useCallback(async (withMode?: VoiceMode) => {
    unlockAudio(); // inside the tap, before any await
    if (withMode) modeRef.current = withMode;
    setError(null);
    setState("starting");
    paused.current = false;
    micMutedRef.current = false;
    setMicMuted(false);
    try {
      config.current = await fetchVoiceConfig();
      const cfg = config.current;
      setStreamOk(!!cfg.stt.streaming);
      if (modeRef.current !== "tap" && !isLive() && cfg.stt.engine === "browser" && !BrowserRecognition) throw new Error("browser_stt_unsupported");

      // Tamil may have its own server voice (Sarvam) while English stays on the browser voice: the server picks per line.
      const serverVoice = cfg.tts.engine === "server" || (langRef.current === "ta" && cfg.tts_ta?.engine === "server");
      let spk: Speaker = serverVoice ? serverSpeaker() : browserSpeaker();
      // A real call (LiveKit) when the server has one: talk any time, Aasan stops the moment you do.
      call.current = null;
      if (cfg.live && modeRef.current !== "tap") {
        try {
          const c = await joinLiveCall(langRef.current, featureRef.current, voiceDebug.log);
          c.onInterrupted = () => interruptRef.current();
          c.onClosed = () => {
            setError("stream_closed");
            stopRef.current();
          };
          call.current = c;
          spk = c.speaker;
          setStreamOk(true);
        } catch (e) {
          const code = (e as Error).message;
          if (["plan_limit", "voice_budget_exceeded", "feature_off", "guardian_consent_required"].includes(code)) throw e;
          voiceDebug.log(`live call unavailable (${code}): using the usual voice`);
        }
      }
      spk.onIdle = () => {
        hostStoppedAt.current = performance.now();
        setState((s) => (s === "speaking" ? idle() : s));
        setSaying("");
        sayingRef.current = "";
        syncPause();
      };
      spk.onError = (code) => setError(code);
      spk.onCaption = (text) => {
        setSaying(text);
        sayingRef.current = text;
      };
      spk.onStart = (text) => {
        if (!firstAudio.current && turnAt.current) {
          firstAudio.current = true;
          voiceDebug.log(`latency: first audio ${Math.round(performance.now() - turnAt.current)}ms after the turn was sent`);
        }
        setSaying(text);
        sayingRef.current = text;
        recentSpoken.current = [...recentSpoken.current, text].slice(-SPOKEN_KEPT);
      };
      speaker.current = spk;

      if (modeRef.current !== "tap") await openMic();
      setState(idle());
      if (modeRef.current !== "tap") mascot.say("🎙️", { ms: 1200 });
    } catch (e) {
      const err = e as Error & { name?: string };
      setError(err.name === "NotAllowedError" ? "mic_denied" : err.message || "voice_failed");
      stop();
    }
  }, [idle, isLive, openMic, stop, syncPause]);

  /** Tap-to-talk: open the mic for one utterance (a tap while the host talks interrupts it first). */
  const listen = useCallback(async () => {
    unlockAudio();
    setError(null);
    if (!speaker.current) return;
    if (speaker.current.busy || streaming.current) interrupt();
    paused.current = false;
    if (micOpen.current) return;
    setState("listening");
    mascot.react("watching", 0);
    try {
      await openMic();
    } catch (e) {
      const err = e as Error & { name?: string };
      closeMic();
      setError(err.name === "NotAllowedError" ? "mic_denied" : err.message || "voice_failed");
      setState(idle());
    }
  }, [closeMic, idle, interrupt, openMic]);

  /** Send what has been heard so far, now (a tap on "Listening… tap to send"). */
  const finish = useCallback(() => {
    if (!micOpen.current) return;
    if (liveStream.current) {
      endLiveTurn();
      return;
    }
    if (recog.current) {
      if (heard.current || partial.current) endUtterance();
      else if (modeRef.current === "tap") {
        closeMic();
        setInterim("");
        setState("ready");
      }
    } else if (clip.current) {
      const c = clip.current;
      clip.current = null;
      if (modeRef.current === "tap") closeMic();
      setState("transcribing");
      void c.stop().then(({ blob, seconds }) => serverTranscribe(blob, seconds)).then(submit).catch(() => setState(idle()));
    } else if (modeRef.current === "tap") {
      closeMic();
      setState("ready");
    }
  }, [closeMic, endLiveTurn, endUtterance, idle, submit]);

  const startRef = useRef(start);
  useEffect(() => {
    stopRef.current = stop;
    startRef.current = start;
  }, [stop, start]);

  // Live: a turn said while the cut-off reply was winding down goes out as soon as the chat is free.
  useEffect(() => {
    busyRef.current = busy;
    if (!busy) {
      clearTimeout(fillerTimer.current);
      awaitingReply.current = false;
    }
    const last = messagesRef.current[messagesRef.current.length - 1];
    if (!busy && fillerOpen.current && !(last?.role === "assistant" && last.content)) {
      // No reply followed the filler (an error, or nothing to say): finish it, or a live call keeps waiting for more.
      fillerOpen.current = false;
      speaker.current?.end?.();
    }
    if (busy || !pendingTurn.current) return;
    const text = pendingTurn.current;
    pendingTurn.current = null;
    void Promise.resolve().then(() => submit(text));
  }, [busy, submit]);

  // Live: speaking another language re-opens the stream in that language.
  const streamLang = useRef(lang);
  useEffect(() => {
    if (streamLang.current === lang) return;
    streamLang.current = lang;
    if (call.current) {
      // The call's listener was set up for the old language: call again in the new one.
      const again = modeRef.current;
      void Promise.resolve().then(() => {
        stopRef.current();
        void startRef.current(again);
      });
      return;
    }
    if (!liveStream.current) return;
    closeMic();
    void Promise.resolve().then(() => openMic().catch((e: Error) => setError(e.message || "voice_failed")));
  }, [closeMic, lang, openMic]);

  // Switching between tap-to-talk and hands-free while voice is on re-plumbs the mic.
  useEffect(() => {
    if (modeRef.current === mode) return;
    modeRef.current = mode;
    if (!speaker.current) return;
    closeMic();
    paused.current = false;
    // The mic is an external system: re-open it after this render rather than setting state inside the effect.
    void Promise.resolve().then(async () => {
      setInterim("");
      if (mode === "tap") return setState((s) => (s === "off" ? s : "ready"));
      setState("listening");
      try {
        await openMic();
        syncPause();
      } catch (e) {
        const err = e as Error & { name?: string };
        setError(err.name === "NotAllowedError" ? "mic_denied" : err.message || "voice_failed");
        setState("ready");
      }
    });
  }, [closeMic, mode, openMic, syncPause]);

  // Reading aloud switched off: stop talking now; the rest of this reply stays on screen only.
  useEffect(() => {
    speakRef.current = speak;
    if (!speak && speaker.current?.busy) {
      hush();
      setState((s) => (s === "speaking" ? idle() : s));
    }
  }, [speak, hush, idle]);

  // Speak the streaming assistant reply sentence by sentence.
  useEffect(() => {
    const last = messages[messages.length - 1];
    streaming.current = !!(last?.role === "assistant" && last.streaming);
    if (last?.role === "assistant" && last.content) {
      awaitingReply.current = false;
      clearTimeout(fillerTimer.current);
    }
    if (last?.role === "assistant" && last.content && turnAt.current && !firstToken.current) {
      firstToken.current = true;
      voiceDebug.log(`latency: first words ${Math.round(performance.now() - turnAt.current)}ms after the turn was sent`);
    }
    if (!on || !speaker.current) return;
    if (!last || last.role !== "assistant") {
      syncPause();
      return;
    }
    if (muted.current === last.id) {
      syncPause();
      return; // the learner stopped this reply
    }
    const st = stream.current;
    if (st.id !== last.id && !(last.streaming && st.id === "live")) {
      // New reply started (ids change from temp → saved on done; track via "live").
      if (last.streaming) {
        st.id = "live";
        // Start speaking on the first clause of a long first sentence: the reply is heard sooner.
        st.splitter = new SentenceStream(cueRef.current, { early: true });
      } else if (st.id !== "live") {
        syncPause();
        return; // historical message, don't read it out
      }
    }
    const sentences = last.streaming ? st.splitter.push(last.content) : st.splitter.flush(last.content);
    // Reading aloud off: the reply is still followed (so turning it back on continues from here), just not spoken.
    const spoken = speakRef.current ? sentences : [];
    for (const s of spoken) speaker.current.speak(s);
    if (spoken.length) {
      fillerOpen.current = false; // the reply carries on from the filler and ends it
      setState("speaking");
    }
    if (!last.streaming) {
      st.id = last.id;
      speaker.current.end?.();
      if (!speaker.current.busy) setState((s) => (s === "thinking" || s === "speaking" ? idle() : s));
    }
    syncPause();
  }, [messages, on, idle, syncPause]);

  // Echo guard + Kili's beak follows the actual voice loudness.
  useEffect(() => {
    if (!on) return;
    let raf = 0;
    const tick = () => {
      const busy = !!speaker.current?.busy;
      if (vad.current) vad.current.machine.sensitivity = busy ? ECHO_GUARD : 1;
      const level = speaker.current?.level() ?? 0;
      useMascot.setState({ mouth: busy ? level : null });
      if (busy && useMascot.getState().mood !== "talking") setMood("talking", 0);
      else if (!busy && useMascot.getState().mood === "talking") setMood("idle");
      syncPause();
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [on, setMood, syncPause]);

  useEffect(() => stop, [stop]);

  const listening = state === "listening" || state === "hearing";
  /** Read a finished line aloud now (e.g. the host's last reply after audio was unlocked by a tap). */
  const speakText = useCallback((text: string) => {
    const spk = speaker.current;
    if (!spk || !text.trim()) return;
    const sentences = new SentenceStream(cueRef.current).flush(text);
    for (const s of sentences) spk.speak(s);
    spk.end?.();
    if (sentences.length) setState("speaking");
  }, []);

  /** Conversation: close the mic without ending voice (Aasan still answers what was already said), or re-open it. */
  const mute = useCallback(async (muteMic: boolean) => {
    if (micMutedRef.current === muteMic || !speaker.current) return;
    micMutedRef.current = muteMic;
    setMicMuted(muteMic);
    if (muteMic) {
      closeMic();
      setInterim("");
      setState((s) => (s === "hearing" ? "listening" : s));
      return;
    }
    unlockAudio();
    try {
      await openMic();
    } catch (e) {
      const err = e as Error & { name?: string };
      setError(err.name === "NotAllowedError" ? "mic_denied" : err.message || "voice_failed");
    }
  }, [closeMic, openMic]);

  /** 0..1 loudness of the learner's mic and of Aasan's voice right now (for a level meter); 0 when unknown. */
  const levels = useCallback(() => ({ mic: vad.current?.level() ?? liveStream.current?.level() ?? 0, voice: speaker.current?.busy ? speaker.current.level() : 0 }), []);

  /** Live conversation is on: hands-free with streamed listening (talk any time to interrupt). */
  const live = on && mode === "handsfree" && streamOk;
  /** Talking over Aasan interrupts it (streamed listening only: the browser recogniser pauses while Aasan talks). */
  const talkOver = live || (on && mode === "conversation" && streamOk);
  /** Aasan is looking something up on the web for this turn (show "Searching the web…"). */
  const searching = on && activity === "searching" && (state === "thinking" || state === "speaking");
  return { state, error, interim, saying, start, stop, active: on, listen, finish, interrupt, hush, listening, speakText, live, talkOver, mute, micMuted, levels, searching };
}
