/** Share images drawn in the browser (no new dependencies): an SVG string, and a PNG made by painting that SVG on a canvas. */

export interface ShareCard { eyebrow: string; title: string; lines: string[]; footer: string; badge?: string }

export const W = 1200;
export const H = 630;

export function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!)
    // XML 1.0 forbids most control characters; drop them so the SVG always parses
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, ""); // eslint-disable-line no-control-regex
}

/** Greedy word wrap by character budget (good enough for a share card); long words are cut, extra lines end in "…". */
export function wrap(text: string, max: number, maxLines: number): string[] {
  const out: string[] = [];
  let line = "";
  for (const raw of text.trim().split(/\s+/)) {
    const word = raw.length > max ? `${raw.slice(0, max - 1)}…` : raw;
    if (!line) line = word;
    else if (line.length + 1 + word.length <= max) line += ` ${word}`;
    else {
      out.push(line);
      line = word;
    }
  }
  if (line) out.push(line);
  if (out.length > maxLines) {
    const kept = out.slice(0, maxLines);
    kept[maxLines - 1] = `${kept[maxLines - 1].slice(0, max - 1)}…`;
    return kept;
  }
  return out;
}

export function shareSvg(c: ShareCard): string {
  const title = wrap(c.title, 30, 3);
  const font = "'Baloo 2', 'Noto Sans Tamil', 'Noto Sans', system-ui, sans-serif";
  const titleY = 250;
  const linesY = titleY + title.length * 66 + 30;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff7ed"/><stop offset="1" stop-color="#fde68a"/></linearGradient></defs>
<rect width="${W}" height="${H}" fill="url(#g)"/>
<rect x="28" y="28" width="${W - 56}" height="${H - 56}" rx="28" fill="none" stroke="#1f2a44" stroke-width="4"/>
<rect x="44" y="44" width="${W - 88}" height="${H - 88}" rx="20" fill="none" stroke="#b8860b" stroke-width="1.5"/>
<circle cx="${W - 150}" cy="150" r="70" fill="#c2410c"/><circle cx="${W - 150}" cy="150" r="56" fill="none" stroke="#fff7ed" stroke-width="3"/>
<text x="${W - 150}" y="168" text-anchor="middle" font-family="${font}" font-size="52" fill="#fff7ed">${esc(c.badge ?? "★")}</text>
<text x="90" y="140" font-family="${font}" font-size="30" font-weight="700" fill="#c2410c" letter-spacing="2">${esc(c.eyebrow)}</text>
${title.map((l, i) => `<text x="90" y="${titleY + i * 66}" font-family="${font}" font-size="56" font-weight="800" fill="#1f2a44">${esc(l)}</text>`).join("\n")}
${c.lines.slice(0, 4).map((l, i) => `<text x="90" y="${linesY + i * 44}" font-family="${font}" font-size="30" fill="#334155">${esc(wrap(l, 60, 1)[0] ?? "")}</text>`).join("\n")}
<text x="90" y="${H - 80}" font-family="${font}" font-size="24" fill="#55607a">${esc(wrap(c.footer, 80, 1)[0] ?? "")}</text>
</svg>`;
}

export function svgToPng(svg: string): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
    const img = new Image();
    img.onload = () => {
      const canvas = Object.assign(document.createElement("canvas"), { width: W, height: H });
      canvas.getContext("2d")?.drawImage(img, 0, 0, W, H);
      URL.revokeObjectURL(url);
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("png_failed"))), "image/png");
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("svg_failed")); };
    img.src = url;
  });
}

export function saveBlob(blob: Blob, name: string) {
  const href = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 2000);
}
