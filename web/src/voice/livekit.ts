/**
 * Live voice over LiveKit (WebRTC), like ChatGPT voice: the learner's mic and Aasan's voice are a real call, so the
 * browser's echo cancelling removes Aasan's voice from the mic, and the voice agent on the server listens (Sarvam,
 * streaming), knows when the turn is over and stops speaking the moment the learner talks.
 *
 * The agent is only the voice. The words still come from each screen's own socket: the agent hands over each finished
 * turn (a StreamEvent, as streamed listening does), and the reply's text is streamed back to the agent to be spoken.
 * So `useVoiceMode` drives a call through the same two seams it already has: a `VoiceStream` for listening and a
 * `Speaker` for speaking.
 */
import { ParticipantKind, Room, RoomEvent, Track, type RemoteParticipant, type TextStreamWriter } from "livekit-client";

import { api, ApiError } from "@/lib/api";

import type { Lang, Speaker } from "./engines";
import type { StreamEvent, VoiceStream } from "./stream";

/** Which screen the call is for (the server checks the org's feature switch for it). */
export type LiveFeature = "mentor" | "live" | "roleplay" | "workshop";

export const EVENT_TOPIC = "aasan.event";
export const SAY_TOPIC = "aasan.say";
export const INTERRUPT_RPC = "aasan.interrupt";
const TRANSCRIPTION_TOPIC = "lk.transcription";
/** The agent joins within a second or two; past this the call is treated as unavailable (voice falls back). */
export const AGENT_JOIN_MS = 12_000;

type AgentEvent = StreamEvent | { type: "state"; state: string } | { type: "said"; id: string } | { type: "interrupted"; id: string };

export interface LiveCall {
  speaker: Speaker & { end(): void; dispose(): void };
  /** Open the mic for listening; events arrive like streamed listening's. `stop()` closes the mic, not the call. */
  listen(onEvent: (e: StreamEvent) => void): Promise<VoiceStream>;
  /** The learner talked over Aasan and the agent stopped speaking: cut the reply too. */
  onInterrupted?: () => void;
  /** The call ended by itself (connection lost, or the agent left). */
  onClosed?: () => void;
}

/** One live voice call. Throws "live_unavailable" (or the server's code) when it can't start, so voice falls back. */
export async function joinLiveCall(lang: Lang, feature: LiveFeature, log: (m: string) => void = () => {}): Promise<LiveCall> {
  let joined: { url: string; token: string };
  try {
    joined = await api<{ url: string; token: string }>("/api/voice/live/token/", { method: "POST", json: { lang, feature } });
  } catch (e) {
    const code = e instanceof ApiError ? String(e.data?.code ?? "live_unavailable") : "live_unavailable";
    throw new Error(code);
  }
  const room = new Room({
    audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    disconnectOnPageLeave: true,
  });
  const audioEls: HTMLMediaElement[] = [];
  let agentState = "listening";
  let onEvent: (e: StreamEvent) => void = () => {};
  let disposed = false;

  const agent = (): RemoteParticipant | undefined =>
    [...room.remoteParticipants.values()].find((p) => p.kind === ParticipantKind.AGENT || p.isAgent) ?? [...room.remoteParticipants.values()][0];

  // ── Speaking: one text stream per reply; the agent speaks it as the words arrive. ──
  let writer: Promise<TextStreamWriter> | null = null;
  let chain: Promise<void> = Promise.resolve();
  let replyId = 0;
  const open = new Set<string>(); // replies sent and not yet said or cut off
  const settle = () => {
    if (!open.size && agentState !== "speaking") call.speaker.onIdle?.();
  };
  const closeWriter = () => {
    const w = writer;
    writer = null;
    chain = chain.then(async () => {
      try {
        await (await w)?.close();
      } catch {
        /* the call is gone */
      }
    });
  };

  const speaker: LiveCall["speaker"] = {
    speak(text) {
      if (disposed || !text.trim()) return;
      if (!writer) {
        const id = String(++replyId);
        open.add(id);
        writer = room.localParticipant.streamText({ topic: SAY_TOPIC, attributes: { id } });
        writer.catch(() => {
          open.delete(id);
          speaker.onError?.("tts_failed");
          settle();
        });
      }
      const w = writer;
      chain = chain.then(async () => {
        try {
          await (await w).write(`${text} `);
        } catch {
          /* closed (cut off) meanwhile */
        }
      });
      speaker.onStart?.(text);
    },
    /** The reply is complete: nothing more will be added to it. */
    end() {
      if (writer) closeWriter();
    },
    cancel() {
      if (writer) closeWriter();
      const had = open.size > 0 || agentState === "speaking";
      open.clear();
      const a = agent();
      if (had && a) void room.localParticipant.performRpc({ destinationIdentity: a.identity, method: INTERRUPT_RPC, payload: "" }).catch(() => {});
    },
    get busy() {
      return open.size > 0 || agentState === "speaking";
    },
    level() {
      return agent()?.audioLevel ?? 0;
    },
    dispose() {
      disposed = true;
      open.clear();
      audioEls.forEach((el) => el.remove());
      void room.disconnect();
    },
  };
  const call: LiveCall = {
    speaker,
    async listen(cb) {
      onEvent = cb;
      await room.localParticipant.setMicrophoneEnabled(true);
      log("live call: mic on");
      return {
        level: () => room.localParticipant.audioLevel ?? 0,
        stop: () => {
          onEvent = () => {};
          void room.localParticipant.setMicrophoneEnabled(false).catch(() => {});
        },
      };
    },
  };

  room.registerTextStreamHandler(EVENT_TOPIC, (reader) => {
    void reader.readAll().then((raw) => {
      let ev: AgentEvent;
      try {
        ev = JSON.parse(raw) as AgentEvent;
      } catch {
        return;
      }
      if (ev.type === "state") {
        agentState = ev.state;
        if (ev.state !== "speaking") settle();
        return;
      }
      if (ev.type === "said" || ev.type === "interrupted") {
        open.delete((ev as { id: string }).id);
        log(`live call: reply ${ev.id} ${ev.type}`);
        if (ev.type === "interrupted") call.onInterrupted?.();
        settle();
        return;
      }
      onEvent(ev);
    });
  });
  // Live captions of what Aasan is saying, in step with its voice (the agent's own transcription of its speech).
  room.registerTextStreamHandler(TRANSCRIPTION_TOPIC, (reader, from) => {
    if (from.identity === room.localParticipant.identity) return;
    const track = reader.info.attributes?.["lk.transcribed_track_id"];
    const mine = [...room.localParticipant.trackPublications.values()].some((p) => p.trackSid === track);
    if (mine) return; // the learner's own words: shown from the interim events instead
    void (async () => {
      let said = "";
      for await (const chunk of reader) {
        said += chunk;
        speaker.onCaption?.(said.trim());
      }
    })();
  });
  room.on(RoomEvent.TrackSubscribed, (track) => {
    if (track.kind !== Track.Kind.Audio) return;
    const el = track.attach(); // an <audio> element: WebRTC playback, which the mic's echo cancelling knows about
    el.style.display = "none";
    document.body.appendChild(el);
    audioEls.push(el);
  });
  room.on(RoomEvent.Disconnected, () => {
    if (!disposed) {
      log("live call: disconnected");
      call.onClosed?.();
    }
  });
  room.on(RoomEvent.ParticipantDisconnected, (p) => {
    if (!disposed && (p.kind === ParticipantKind.AGENT || p.isAgent)) call.onClosed?.();
  });

  await room.connect(joined.url, joined.token);
  log("live call: connected, waiting for Aasan");
  await new Promise<void>((resolve, reject) => {
    if (agent()) return resolve();
    const t = setTimeout(() => {
      room.off(RoomEvent.ParticipantConnected, joinedNow);
      void room.disconnect();
      reject(new Error("live_unavailable"));
    }, AGENT_JOIN_MS);
    function joinedNow() {
      clearTimeout(t);
      room.off(RoomEvent.ParticipantConnected, joinedNow);
      resolve();
    }
    room.on(RoomEvent.ParticipantConnected, joinedNow);
  });
  await room.startAudio().catch(() => {});
  log("live call: Aasan joined");
  return call;
}
