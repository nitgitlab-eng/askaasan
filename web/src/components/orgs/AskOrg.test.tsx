import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { renderPage } from "@/test/render";

import { AskOrg } from "./AskOrg";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

function askIt(question = "Who is stuck right now?") {
  fireEvent.change(screen.getByRole("textbox", { name: "Ask about your organisation" }), { target: { value: question } });
  fireEvent.click(screen.getByRole("button", { name: /send/i }));
}

describe("AskOrg", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
  });

  it("sends the question and shows the chart plus the first-name table", async () => {
    vi.mocked(api).mockResolvedValue({
      supported: true, title: "Learners needing attention", metric: "stuck", group_by: "class", chart: "bar", unit: "", note: "", class: null,
      data: [{ label: "7-A", value: 1 }, { label: "7-B", value: 0 }],
      table: { columns: ["learner", "class", "reasons"], rows: [["John", "7-A", "inactive, overdue"]] },
    } as never);
    renderPage(<AskOrg slug="acme" />);
    askIt();
    expect(await screen.findByText("Learners needing attention")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/api/orgs/acme/ask/", { method: "POST", json: { question: "Who is stuck right now?" } });
    expect(screen.getByRole("columnheader", { name: "Learner" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "John" })).toBeInTheDocument();
    expect(screen.getByText(/fixed set of measures/)).toBeInTheDocument();
  });

  it("table-only answers and unsupported questions", async () => {
    vi.mocked(api).mockResolvedValueOnce({
      supported: true, title: "Overdue", metric: "overdue", group_by: "assignment", chart: "table", unit: "", note: "", data: [{ label: "Fire", value: 1 }],
      table: { columns: ["learner", "assignment"], rows: [["John", "Fire"]] }, class: "7-A",
    } as never);
    renderPage(<AskOrg slug="acme" />);
    askIt("Which assignments are overdue?");
    expect(await screen.findByRole("cell", { name: "Fire" })).toBeInTheDocument();
    expect(screen.getByText(/Only class 7-A/)).toBeInTheDocument();
    vi.mocked(api).mockResolvedValueOnce({ supported: false, note: "" } as never);
    askIt("What is everyone's salary?");
    expect(await screen.findByText(/can't be answered from your organisation's data/)).toBeInTheDocument();
  });

  it("explains budget and scope refusals", async () => {
    vi.mocked(api).mockRejectedValueOnce(new ApiError(429, { code: "ai_budget_exceeded" }));
    renderPage(<AskOrg slug="acme" />);
    askIt();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    vi.mocked(api).mockRejectedValueOnce(new ApiError(400, { code: "bad_scope" }));
    askIt();
    expect(await screen.findByText("That class or assignment isn't one you can see.")).toBeInTheDocument();
  });
});
