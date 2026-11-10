import { useState, type ComponentProps } from "react";
import { useTranslation } from "react-i18next";

/** An image on another site. Fetching it would tell that site the reader is here (and whatever the URL encodes). */
function isExternalSrc(src: string | undefined) {
  if (!src) return false;
  try {
    return new URL(src, window.location.href).origin !== window.location.origin;
  } catch {
    return true;
  }
}

/** Model-written image: shown only after the reader asks for it, so AI output can't make the browser call out on its own. */
export function ClickToLoadImg({ src, alt, node: _node, ...rest }: ComponentProps<"img"> & { node?: unknown }) {
  const { t } = useTranslation();
  const [show, setShow] = useState(false);
  const url = typeof src === "string" ? src : undefined;
  if (!isExternalSrc(url) || show) return <img src={url} alt={alt} {...rest} />;
  let host = "";
  try {
    host = new URL(url!).host;
  } catch {
    /* unparsable: no host to show */
  }
  return (
    <button type="button" onClick={() => setShow(true)} className="my-1 inline-flex items-center gap-1 rounded-lg border border-line px-2 py-1 text-xs text-muted hover:border-accent">
      🖼️ {t("md.loadImage", { host: host || "?" })}{alt ? ` (${alt})` : ""}
    </button>
  );
}
