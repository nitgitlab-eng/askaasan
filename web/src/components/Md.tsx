import { lazy, Suspense } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { ClickToLoadImg } from "./ClickToLoadImg";

const MathMd = lazy(() => import("./MathMd"));

const AI_COMPONENTS: Components = { img: ClickToLoadImg };

/**
 * Markdown with tables; maths ($x^2$ inline, $$…$$ display) is rendered when present. No raw HTML.
 * `ai` marks model-generated text (mentor, tutor, role-play): images from other sites wait for a click.
 * Authored lesson text leaves it off and keeps its pictures.
 */
export function Md({ children, ai = false }: { children: string; ai?: boolean }) {
  const components = ai ? AI_COMPONENTS : undefined;
  const plain = <Markdown remarkPlugins={[remarkGfm]} components={components}>{children}</Markdown>;
  return children.includes("$") ? <Suspense fallback={plain}><MathMd components={components}>{children}</MathMd></Suspense> : plain;
}
