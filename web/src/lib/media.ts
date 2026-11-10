import { useAuth } from "@/stores/auth";

import { api, ApiError } from "./api";

export interface MediaAsset { id: number; url: string; width: number; height: number; kind: "upload" | "generated"; prompt: string; alt: string }

export const media = {
  async upload(file: File, alt = ""): Promise<MediaAsset> {
    const form = new FormData();
    form.append("file", file);
    form.append("alt", alt);
    const r = await fetch("/api/media/upload/", { method: "POST", body: form, headers: { Authorization: `Bearer ${useAuth.getState().access}` } });
    const d = await r.json().catch(() => null);
    if (!r.ok) throw new ApiError(r.status, d);
    return d;
  },
  generate: (prompt: string, alt = "") => api<MediaAsset>("/api/media/generate/", { method: "POST", json: { prompt, alt } }),
  mine: () => api<MediaAsset[]>("/api/media/mine/"),
};
