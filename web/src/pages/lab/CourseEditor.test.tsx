import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { renderPage } from "@/test/render";

import CourseEditor from "./CourseEditor";

const course = {
  id: 7, title: "UPI safety", goal: "", description: "", level: "beginner", language: "en", cover_emoji: "📘", status: "ready", error: "",
  visibility: "private", catalog_status: "none", catalog_note: "", published_at: null, share_token: "s", learners: 0,
  sections: [{ id: 11, title: "Basics", summary: "", subsections: [{ id: 21, title: "What is UPI", objective: "", lesson_status: "ready", error: "", activities: 0 }] }],
  history: { can_undo: false, can_redo: false, undo_label: "", redo_label: "" },
};

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const deletes = () => vi.mocked(api).mock.calls.filter((c) => (c[1] as { method?: string } | undefined)?.method === "DELETE").map((c) => c[0]);

describe("Creator Lab course editor", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    vi.mocked(api).mockImplementation((async (path: string, init?: { method?: string }) => (path === "/api/lab/courses/7/" && !init?.method ? course : init?.method === "DELETE" ? course : null)) as never);
  });

  it("the icon-only delete-course button has an accessible name (R27)", async () => {
    renderPage(<CourseEditor />, { route: "/lab/7", path: "/lab/:id" });
    expect(await screen.findByRole("button", { name: "Delete course" })).toBeInTheDocument();
  });

  it("deleting a section asks first; Cancel deletes nothing (R23)", async () => {
    renderPage(<CourseEditor />, { route: "/lab/7", path: "/lab/:id" });
    await screen.findByDisplayValue("Basics");
    const [sectionDelete] = screen.getAllByRole("button", { name: "Delete" });
    fireEvent.click(sectionDelete);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Basics");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(deletes()).toEqual([]);
  });

  it("deleting a lesson asks first, then deletes only that lesson (R23)", async () => {
    renderPage(<CourseEditor />, { route: "/lab/7", path: "/lab/:id" });
    await screen.findByText("What is UPI");
    const buttons = screen.getAllByRole("button", { name: "Delete" });
    fireEvent.click(buttons[buttons.length - 1]);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("What is UPI");
    fireEvent.click(within(dialog).getByRole("button", { name: "OK" }));
    await waitFor(() => expect(deletes()).toEqual(["/api/lab/subsections/21/"]));
  });
});

describe("Reset share link (H45)", () => {
  it("asks first, then shows the new link from the server", async () => {
    vi.mocked(api).mockImplementation((async (path: string, init?: { method?: string }) => {
      if (path === "/api/lab/courses/7/" && !init?.method) return { ...course, visibility: "link", published_at: "2026-10-01T00:00:00Z", share_token: "old-token" };
      if (path === "/api/lab/courses/7/share/rotate/") return { share_token: "new-token" };
      return null;
    }) as never);
    renderPage(<CourseEditor />, { route: "/lab/7", path: "/lab/:id" });
    expect(await screen.findByText(/\/s\/old-token/)).toBeInTheDocument();
    expect(screen.getByText(/Unpublishing and publishing again also gives the course a new link/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reset share link" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api).not.toHaveBeenCalledWith("/api/lab/courses/7/share/rotate/", expect.anything());

    fireEvent.click(screen.getByRole("button", { name: "Reset share link" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Reset share link" }));
    expect(await screen.findByText(/\/s\/new-token/)).toBeInTheDocument();
    expect(screen.queryByText(/\/s\/old-token/)).toBeNull();
    expect(api).toHaveBeenCalledWith("/api/lab/courses/7/share/rotate/", { method: "POST" });
    expect(screen.getByText(/The old link no longer works/)).toBeInTheDocument();
  });
});
