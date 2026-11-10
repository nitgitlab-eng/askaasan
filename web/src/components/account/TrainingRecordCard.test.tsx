import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { downloadFile } from "@/lib/download";
import { renderPage } from "@/test/render";

import { TrainingRecordCard } from "./TrainingRecordCard";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));
vi.mock("@/lib/download", () => ({ downloadFile: vi.fn(async () => undefined) }));

const REC = {
  id: 1, learner: "Kavya", email: "k@x.in", kind: "course", title: "Fire safety", assigned_at: null, started_at: null,
  completed_at: "2026-10-01T10:00:00Z", score: 92, minutes: 30, certificate_code: "ABC", verify_url: "", org: "Acme", backfilled: false,
};

describe("TrainingRecordCard", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    vi.mocked(downloadFile).mockClear();
  });

  it("lists the learner's records and downloads Excel and PDF", async () => {
    vi.mocked(api).mockResolvedValue([REC] as never);
    renderPage(<TrainingRecordCard />);
    expect(await screen.findByText("Fire safety")).toBeInTheDocument();
    expect(screen.getByText(/Acme · Completed/)).toHaveTextContent("Score 92%");
    fireEvent.click(screen.getByRole("button", { name: /Excel/ }));
    fireEvent.click(screen.getByRole("button", { name: /PDF/ }));
    await waitFor(() => expect(downloadFile).toHaveBeenCalledWith("/api/orgs/me/training-record.xlsx", "my-training-record.xlsx"));
    expect(downloadFile).toHaveBeenCalledWith("/api/orgs/me/training-record.pdf", "my-training-record.pdf");
  });

  it("renders nothing without records", async () => {
    vi.mocked(api).mockResolvedValue([] as never);
    const { container } = renderPage(<TrainingRecordCard />);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/orgs/me/training-record/"));
    expect(container).toBeEmptyDOMElement();
  });
});
