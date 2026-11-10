import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Caption } from "./Caption";

describe("workshop caption", () => {
  it("lists the web pages the host's search used, once the reply is finished", () => {
    const host = { id: "a1", role: "assistant" as const, content: "UPI handled 18 billion payments last month.", citations: [{ kind: "web" as const, title: "NPCI statistics", url: "https://www.npci.org.in/statistics" }] };
    const { rerender } = render(<Caption messages={[{ ...host, streaming: true }]} busy />);
    expect(screen.queryByRole("link", { name: "NPCI statistics" })).not.toBeInTheDocument();
    rerender(<Caption messages={[host]} busy={false} />);
    expect(screen.getByRole("link", { name: "NPCI statistics" })).toHaveAttribute("href", "https://www.npci.org.in/statistics");
  });
});
