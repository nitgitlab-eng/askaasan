import { afterEach, describe, expect, it, vi } from "vitest";

import { Downsampler, FRAME_SAMPLES } from "./stream";

describe("Downsampler (mic → 16 kHz PCM16 frames of ~100 ms)", () => {
  it("48 kHz: one second of audio becomes ten 1600-sample frames", () => {
    const d = new Downsampler(48000);
    const frames = [];
    for (let i = 0; i < 48000 / 2048 + 1; i++) frames.push(...d.push(new Float32Array(2048).fill(0.5)));
    expect(frames.length).toBe(10);
    expect(frames.every((f) => f.length === FRAME_SAMPLES)).toBe(true);
    expect(Math.abs(frames[0][100] - 16383)).toBeLessThanOrEqual(1);
  });

  it("44.1 kHz keeps the rate across chunk edges, and clips to ±1", () => {
    const d = new Downsampler(44100);
    let n = 0;
    for (let i = 0; i < 101; i++) n += d.push(new Float32Array(441).fill(2)).length;
    expect(n).toBe(10); // 44541 samples → ~16160 → 10 whole frames
    const [f] = new Downsampler(16000).push(new Float32Array(FRAME_SAMPLES).fill(-3));
    expect(f[0]).toBe(-32768);
  });
});

// ── openVoiceStream over a fake socket and a fake mic (ScriptProcessor path). ─────────────────────────────────
class FakeSocket {
  static all: FakeSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  sent: (string | ArrayBufferView)[] = [];
  binaryType = "";
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeSocket.all.push(this);
    queueMicrotask(() => {
      this.readyState = 1;
      this.onopen?.();
    });
  }
  send(d: string | ArrayBufferView) {
    this.sent.push(d);
  }
  close() {
    this.readyState = 3;
  }
  server(ev: object) {
    this.onmessage?.({ data: JSON.stringify(ev) });
  }
}
const proc = { onaudioprocess: null as null | ((e: { inputBuffer: { getChannelData: () => Float32Array } }) => void) };
const node = () => ({ connect: () => {}, disconnect: () => {} });
class FakeAudioContext {
  sampleRate = 16000;
  state = "running";
  destination = {};
  createMediaStreamSource = () => node();
  createGain = () => ({ ...node(), gain: { value: 1 } });
  createScriptProcessor = () => Object.assign(proc, node());
  close = async () => {};
  resume = async () => {};
}

describe("openVoiceStream", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  async function open(onEvent = (_e: unknown) => {}) {
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.stubGlobal("AudioContext", FakeAudioContext);
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })) },
      configurable: true,
    });
    const { useAuth } = await import("@/stores/auth");
    useAuth.setState({ access: "tok" } as never);
    const api = await import("@/lib/api");
    vi.spyOn(api, "ensureFreshAccess").mockResolvedValue("tok");
    const { openVoiceStream } = await import("./stream");
    FakeSocket.all = [];
    const p = openVoiceStream("ta", onEvent);
    await vi.waitFor(() => expect(FakeSocket.all.length).toBe(1));
    const sock = FakeSocket.all[0];
    await vi.waitFor(() => expect(sock.sent[0]).toBe(JSON.stringify({ type: "auth", token: "tok" })));
    return { p, sock };
  }

  it("authenticates, starts in the learner's language, then streams 100 ms PCM16 frames", async () => {
    const events: unknown[] = [];
    const { p, sock } = await open((e) => events.push(e));
    expect(sock.url).toMatch(/\/ws\/voice-stream\/$/);
    sock.server({ type: "ready" });
    expect(sock.sent[1]).toBe(JSON.stringify({ type: "start", lang: "ta" }));
    sock.server({ type: "started" });
    const s = await p;
    proc.onaudioprocess!({ inputBuffer: { getChannelData: () => new Float32Array(2048).fill(0.1) } });
    const frames = sock.sent.filter((x) => typeof x !== "string") as Int16Array[];
    expect(frames).toHaveLength(1);
    expect(frames[0].length).toBe(FRAME_SAMPLES);
    sock.server({ type: "interim", text: "வணக்கம்" });
    sock.server({ type: "error", code: "session_limit" }); // reconnectable: not surfaced
    expect(events).toEqual([{ type: "interim", text: "வணக்கம்" }]);
    s.stop();
    expect(sock.sent.at(-1)).toBe(JSON.stringify({ type: "stop" }));
  });

  it("a fatal error before it starts rejects with the code", async () => {
    const { p, sock } = await open();
    sock.server({ type: "error", code: "streaming_unavailable" });
    await expect(p).rejects.toThrow("streaming_unavailable");
  });
});
