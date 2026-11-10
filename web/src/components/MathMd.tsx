import "katex/dist/katex.min.css";

import Markdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

/** Markdown + maths. Loaded only for text that contains "$" (KaTeX is large). */
export default function MathMd({ children, components }: { children: string; components?: Components }) {
  return <Markdown remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: true }]]} rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: "ignore" }]]} components={components}>{children}</Markdown>;
}
