import { refreshTokens } from "./api";
import { useAuth } from "@/stores/auth";

/** Authenticated file download (exports are permission-checked, so a plain <a href> wouldn't carry the token). */
export async function downloadFile(url: string, fallbackName: string) {
  const get = () => fetch(url, { headers: { Authorization: `Bearer ${useAuth.getState().access ?? ""}` } });
  let res = await get();
  if (res.status === 401 && (await refreshTokens())) res = await get();
  if (!res.ok) throw new Error(`download_failed_${res.status}`);
  const cd = res.headers.get("Content-Disposition") ?? "";
  const star = /filename\*=UTF-8''([^;]+)/i.exec(cd)?.[1];
  const name = star ? decodeURIComponent(star) : /filename="([^"]+)"/i.exec(cd)?.[1] ?? fallbackName;
  const href = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 2000);
}
