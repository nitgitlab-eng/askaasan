import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WebSources } from "./WebSources";

describe("<WebSources>", () => {
  it("lists web pages as safe external links and skips document citations", () => {
    render(
      <WebSources
        citations={[
          { n: 1, page: 2, chunk_id: 3, snippet: "doc" },
          { kind: "web", title: "The Hindu", url: "https://www.thehindu.com/gold" },
          { kind: "web", title: "", url: "https://www.rbi.org.in/x" },
        ]}
      />,
    );
    const links = screen.getAllByRole("link");
    expect(links.map((a) => a.textContent)).toEqual(["The Hindu", "rbi.org.in"]);
    for (const a of links) {
      expect(a.getAttribute("target")).toBe("_blank");
      expect(a.getAttribute("rel")).toContain("noopener");
    }
  });

  it("never renders a non-http link", () => {
    const { container } = render(<WebSources citations={[{ kind: "web", title: "x", url: "javascript:alert(1)" }]} />);
    expect(container.innerHTML).toBe("");
  });
});
