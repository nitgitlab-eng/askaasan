// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Src = Record<string, any>;

export function youtubeId(url: string): string {
  const s = url.trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(s)) return s;
  const m = s.match(/(?:youtu\.be\/|youtube(?:-nocookie)?\.com\/(?:watch\?(?:.*&)?v=|embed\/|shorts\/|live\/))([A-Za-z0-9_-]{11})/);
  return m ? m[1] : "";
}
export const toSec = (v: string) => {
  const p = v.trim().split(":").map(Number);
  if (p.some(Number.isNaN)) return 0;
  return p.length === 2 ? p[0] * 60 + p[1] : p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] || 0;
};
export const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

export const emptyVideo = (): Src => ({ type: "video", title: "", prompt: "", video_id: "", start: 0, end: 0, checkpoints: [], explanation: "" });
export const emptyHotspot = (): Src => ({ type: "hotspot", title: "", prompt: "", image: "", targets: [], explanation: "" });
