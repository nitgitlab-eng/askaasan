/** On-device helpers: nothing leaves the browser until a snapshot is deliberately sent. */

const TW = 32, TH = 24;

/** Tiny grayscale thumbnail used only for change detection. */
export function thumb(video: HTMLVideoElement, canvas: HTMLCanvasElement): Uint8ClampedArray | null {
  if (!video.videoWidth) return null;
  canvas.width = TW;
  canvas.height = TH;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0, TW, TH);
  const px = ctx.getImageData(0, 0, TW, TH).data;
  const g = new Uint8ClampedArray(TW * TH);
  for (let i = 0; i < g.length; i++) g[i] = (px[i * 4] * 299 + px[i * 4 + 1] * 587 + px[i * 4 + 2] * 114) / 1000;
  return g;
}

export function diff(a: Uint8ClampedArray | null, b: Uint8ClampedArray | null): number {
  if (!a || !b) return 255;
  let s = 0;
  for (let i = 0; i < a.length; i++) s += Math.abs(a[i] - b[i]);
  return s / a.length;
}

/** A JPEG snapshot, longest side ≤ 1024 px — enough to read handwriting and code, small enough to send fast. */
export function snapshot(video: HTMLVideoElement, canvas: HTMLCanvasElement, maxSide = 1024): string | null {
  const { videoWidth: w, videoHeight: h } = video;
  if (!w || !h) return null;
  const k = Math.min(1, maxSide / Math.max(w, h));
  canvas.width = Math.round(w * k);
  canvas.height = Math.round(h * k);
  canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.72);
}

export interface Detector { stop(): void; markSent(): void }

/**
 * Calls onChange when the picture has changed meaningfully since the last snapshot AND has
 * been held still (so we don't send a blurry page mid-flip). Throttled to one every minGapMs.
 */
export function watchChanges(video: HTMLVideoElement, onChange: () => void, { minGapMs = 5000, everyMs = 600 } = {}): Detector {
  const c = document.createElement("canvas");
  let prev: Uint8ClampedArray | null = null;
  let sent: Uint8ClampedArray | null = null;
  let stillSince: number | null = null;
  let lastSentAt = 0;
  const id = setInterval(() => {
    const cur = thumb(video, c);
    if (!cur) return;
    const now = Date.now();
    const motion = diff(cur, prev);
    prev = cur;
    stillSince = motion < 3 ? (stillSince ?? now) : null;
    if (stillSince && now - stillSince > 1200 && now - lastSentAt > minGapMs && diff(cur, sent) > 10) {
      sent = cur;
      lastSentAt = now;
      onChange();
    }
  }, everyMs);
  return {
    stop: () => clearInterval(id),
    markSent: () => {
      sent = thumb(video, c);
      lastSentAt = Date.now();
    },
  };
}
