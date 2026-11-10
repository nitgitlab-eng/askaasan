import { useEffect, useId, useState } from "react";

/** Lazy-loads mermaid and renders a diagram; falls back to the source text. */
export function Mermaid({ source }: { source: string }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    void import("mermaid").then(async ({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral", fontFamily: "inherit" });
      try {
        const { svg } = await mermaid.render(`m${id}`, source);
        if (alive) setSvg(svg);
      } catch {
        if (alive) setFailed(true);
      }
    });
    return () => {
      alive = false;
    };
  }, [id, source]);
  if (failed) return <pre className="overflow-x-auto rounded-xl bg-surface-2 p-3 text-sm">{source}</pre>;
  if (!svg) return <div className="h-32 animate-pulse rounded-xl bg-surface-2" />;
  // mermaid output is sanitised (securityLevel strict).
  return <div className="flex justify-center overflow-x-auto rounded-xl bg-white p-3 [&_svg]:max-w-full" dangerouslySetInnerHTML={{ __html: svg }} />;
}
