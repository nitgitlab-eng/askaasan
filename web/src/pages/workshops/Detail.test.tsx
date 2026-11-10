import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { apiRoutes, renderPage } from "@/test/render";

import WorkshopDetailPage from "./Detail";
import WorkshopLobbyPage from "./Lobby";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));
const navigate = vi.fn();
vi.mock("react-router-dom", async (orig) => ({ ...(await orig<typeof import("react-router-dom")>()), useNavigate: () => navigate }));

const NOW = Date.parse("2026-10-18T10:00:00Z");
const at = (mins: number) => new Date(NOW + mins * 60_000).toISOString();
const detail = (over: object = {}, start = 120) => ({
  id: 4, workshop: { slug: "prompting", title: "Prompt Engineering", summary: "Write, test and improve prompts.", level: "beginner", duration_minutes: 90 },
  starts_at: at(start), status: "scheduled", price_paise: 0, enrolled: false, session_id: null, audience: "public", my_status: "none", seats_left: 12, proctoring: "off",
  lobby_opens_at: at(start - 15), join_opens_at: at(start - 15), join_closes_at: at(start + 15),
  prerequisites: [{ key: "chat", label: "An AI chat app you can use", how_to_md: "Open **ChatGPT** or Gemini in a new tab." }],
  tracked: ["answers", "steps_done", "help_requests", "tab_visibility"], certificate: true,
  agenda: [{ title: "What a prompt is", minutes: 20, kind: "teach" }, { title: "Write your own", minutes: 40, kind: "diy" }, { title: "Final", minutes: 30, kind: "assessment" }],
  ...over,
});

const detailPage = () => renderPage(<WorkshopDetailPage />, { route: "/workshops/4", path: "/workshops/:runId" });
const lobbyPage = () => renderPage(<WorkshopLobbyPage />, { route: "/workshops/4/lobby", path: "/workshops/:runId/lobby" });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  navigate.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
  delete window.Razorpay;
});

describe("run detail", () => {
  it("shows the summary, agenda, prerequisites and what's tracked", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/workshops/runs/4/": detail() }) as typeof api);
    detailPage();
    expect(await screen.findByRole("heading", { name: "Prompt Engineering" })).toBeInTheDocument();
    const agenda = screen.getByRole("list", { name: "What you'll do" });
    expect(within(agenda).getAllByRole("listitem")).toHaveLength(3);
    expect(agenda).toHaveTextContent("Write your own");
    expect(agenda).toHaveTextContent("40 min");
    expect(screen.getByText("An AI chat app you can use")).toBeInTheDocument();
    expect(screen.getByText(/no camera and no tab tracking/i)).toBeInTheDocument();
    expect(screen.getByText("12 seats left")).toBeInTheDocument();
    // the how-to is folded away under the prerequisite
    expect(screen.getByText("How to get ready").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("ChatGPT").tagName).toBe("STRONG");
    const tracked = screen.getByRole("list", { name: "What we track" });
    expect(within(tracked).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Your answers", "Steps you tick", "Help requests (a short summary, never the screenshot)", "Switching tabs"]);
    expect(screen.getByText(/certificate from Aasan/i)).toBeInTheDocument();
  });

  it("enrols for free, then offers the calendar file and the countdown", async () => {
    let enrolled = false;
    const enroll = vi.fn(() => ((enrolled = true), { enrolled: true }));
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/workshops/runs/4/enroll/": enroll,
      "/api/workshops/runs/4/": () => detail(enrolled ? { enrolled: true, my_status: "enrolled" } : {}),
    }) as typeof api);
    const createUrl = vi.fn(() => "blob:ics");
    Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: vi.fn() });
    detailPage();
    fireEvent.click(await screen.findByRole("button", { name: /enrol for free/i }));
    expect(await screen.findByText("You're enrolled!")).toBeInTheDocument();
    expect(enroll).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("timer")).toHaveTextContent("2 h 0 min");
    fireEvent.click(screen.getByRole("button", { name: /add to calendar/i }));
    const blob = (createUrl.mock.calls[0] as unknown as [Blob])[0];
    expect(blob.type).toMatch(/text\/calendar/);
    expect(await blob.text()).toContain("SUMMARY:Prompt Engineering");
  });

  it("pays in Razorpay Checkout with the server's order, then verifies", async () => {
    let paid = false;
    const verify = vi.fn(() => ((paid = true), { ok: true }));
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/workshops/runs/4/checkout/": { order_id: "order_1", amount: 49900, currency: "INR", key_id: "rzp_test", name: "Aasan", description: "Workshop", mode: "test", prefill: { email: "a@b.in", name: "A" } },
      "/api/billing/verify/": verify,
      "/api/workshops/runs/4/": () => detail(paid ? { price_paise: 49900, enrolled: true, my_status: "enrolled" } : { price_paise: 49900 }),
    }) as typeof api);
    let opts: { order_id: string; amount: number; handler: (r: object) => void } | null = null;
    window.Razorpay = class {
      constructor(o: typeof opts) {
        opts = o;
      }
      on() {}
      open() {
        opts!.handler({ razorpay_order_id: "order_1", razorpay_payment_id: "pay_1", razorpay_signature: "sig" });
      }
    } as unknown as typeof window.Razorpay;
    detailPage();
    fireEvent.click(await screen.findByRole("button", { name: /pay ₹499 & enrol/i }));
    expect(await screen.findByText("You're enrolled!")).toBeInTheDocument();
    expect(opts!.order_id).toBe("order_1");
    expect(opts!.amount).toBe(49900);
    expect(verify).toHaveBeenCalledWith(expect.objectContaining({ json: { razorpay_order_id: "order_1", razorpay_payment_id: "pay_1", razorpay_signature: "sig" } }));
  });

  it("says when the payment is still being confirmed, and stays quiet when Checkout is closed", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/workshops/runs/4/checkout/": { order_id: "order_1", amount: 49900, currency: "INR", key_id: "k", name: "", description: "", mode: "test", prefill: { email: "", name: "" } },
      "/api/billing/verify/": () => {
        throw new ApiError(409, { code: "payment_pending" });
      },
      "/api/workshops/runs/4/": detail({ price_paise: 49900 }),
    }) as typeof api);
    let dismiss = false;
    window.Razorpay = class {
      o: { handler: (r: object) => void; modal: { ondismiss: () => void } };
      constructor(o: { handler: (r: object) => void; modal: { ondismiss: () => void } }) {
        this.o = o;
      }
      on() {}
      open() {
        if (dismiss) this.o.modal.ondismiss();
        else this.o.handler({ razorpay_order_id: "order_1", razorpay_payment_id: "p", razorpay_signature: "s" });
      }
    } as unknown as typeof window.Razorpay;
    detailPage();
    fireEvent.click(await screen.findByRole("button", { name: /pay ₹499/i }));
    expect(await screen.findByRole("status")).toHaveTextContent(/payment received/i);

    dismiss = true;
    fireEvent.click(screen.getByRole("button", { name: /pay ₹499/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /pay ₹499/i })).not.toBeDisabled());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("payment taken but no seat (the run filled meanwhile): says a refund is coming", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/workshops/runs/4/checkout/": { order_id: "order_1", amount: 49900, currency: "INR", key_id: "k", name: "", description: "", mode: "test", prefill: { email: "", name: "" } },
      "/api/billing/verify/": () => {
        throw new ApiError(409, { code: "run_full" });
      },
      "/api/workshops/runs/4/": detail({ price_paise: 49900 }),
    }) as typeof api);
    window.Razorpay = class {
      o: { handler: (r: object) => void };
      constructor(o: { handler: (r: object) => void }) {
        this.o = o;
      }
      on() {}
      open() {
        this.o.handler({ razorpay_order_id: "order_1", razorpay_payment_id: "p", razorpay_signature: "s" });
      }
    } as unknown as typeof window.Razorpay;
    detailPage();
    fireEvent.click(await screen.findByRole("button", { name: /pay ₹499/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/payment was received.*our team will refund you/i);
  });

  it.each([
    ["already_enrolled", /already enrolled/i],
    ["bad_gst_details", /gst details/i],
    ["too_many_orders", /too many attempts/i],
    ["payments_unavailable", /payments aren't switched on/i],
    ["gateway_error", /razorpay is not responding/i],
  ])("maps checkout code %s", async (code, text) => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/workshops/runs/4/checkout/": () => {
        throw new ApiError(409, { code });
      },
      "/api/workshops/runs/4/": detail({ price_paise: 49900 }),
    }) as typeof api);
    detailPage();
    fireEvent.click(await screen.findByRole("button", { name: /pay ₹499/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("maps a full run at checkout to a clear message", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/workshops/runs/4/checkout/": () => {
        throw new ApiError(409, { code: "run_full" });
      },
      "/api/workshops/runs/4/": detail({ price_paise: 49900 }),
    }) as typeof api);
    detailPage();
    fireEvent.click(await screen.findByRole("button", { name: /pay ₹499/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/is full/i);
  });

  it.each([
    [{ seats_left: 0 }, 120, /this workshop is full/i],
    [{}, -30, /enrolment has closed/i],
    [{ status: "cancelled" }, 120, /was cancelled/i],
  ])("no enrol button when %o (start %i min)", async (over, start, text) => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/workshops/runs/4/": detail(over, start) }) as typeof api);
    detailPage();
    expect((await screen.findAllByText(text)).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /enrol/i })).toBeNull();
  });
});

describe("lobby", () => {
  const enrolled = { enrolled: true, my_status: "enrolled" };

  it("before the lobby opens: says when, with a countdown to the doors", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/workshops/runs/4/": detail(enrolled, 120) }) as typeof api);
    lobbyPage();
    expect(await screen.findByText(/the lobby opens at/i)).toBeInTheDocument();
    expect(screen.getByRole("timer")).toHaveTextContent("1 h 45 min");
    expect(screen.queryByRole("button", { name: /join now/i })).toBeNull();
  });

  it("in the lobby: counts down to the start, previews the checklist and lets prep start", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/workshops/runs/4/session/": { id: 21 },
      "/api/workshops/runs/4/": detail(enrolled, 10),
    }) as typeof api);
    lobbyPage();
    expect(await screen.findByRole("timer")).toHaveTextContent("10 min 00 s");
    expect(screen.getByText("An AI chat app you can use")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /join now/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /start your prep/i }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/workshops/session/21"));
  });

  it("the countdown ticks, and at the start time Join opens the session", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/workshops/runs/4/session/": { id: 21 },
      "/api/workshops/runs/4/": detail(enrolled, 1),
    }) as typeof api);
    lobbyPage();
    expect(await screen.findByRole("timer")).toHaveTextContent("1 min 00 s");
    vi.setSystemTime(NOW + 61_000);
    fireEvent.click(await screen.findByRole("button", { name: /join now/i }, { timeout: 2500 }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/workshops/session/21"));
    expect(screen.getByText(/joining stays open until/i)).toBeInTheDocument();
  });

  it("after the join window: joining closed", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/workshops/runs/4/": detail(enrolled, -20) }) as typeof api);
    lobbyPage();
    expect(await screen.findByText("Joining closed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /join now/i })).toBeNull();
  });

  it("a session already started can be continued even after the window", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/workshops/runs/4/": detail({ ...enrolled, session_id: 33 }, -60) }) as typeof api);
    lobbyPage();
    fireEvent.click(await screen.findByRole("button", { name: /continue/i }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/workshops/session/33"));
  });

  it("not enrolled: points back to the workshop page", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/workshops/runs/4/": detail({}, 10) }) as typeof api);
    lobbyPage();
    expect(await screen.findByText(/not enrolled/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /see the workshop/i })).toHaveAttribute("href", "/workshops/4");
  });
});

describe("tracking notice and layout (M5 polish)", () => {
  it("org runs carry the institution line on the run page, worded like the prerequisites screen", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/workshops/runs/4/": detail({ audience: "org", proctoring: "activity" }) }) as typeof api);
    detailPage();
    const box = await screen.findByTestId("proctor-box");
    expect(within(box).getByRole("heading", { name: "What we track" })).toBeInTheDocument();
    expect(within(box).getByTestId("org-notice")).toHaveTextContent("Your institution can see your progress, answers, scores, help summaries and attention activity during this workshop.");
    expect(box).toHaveTextContent("Never the camera or microphone recording.");
  });

  it("public runs show no institution line", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/workshops/runs/4/": detail() }) as typeof api);
    detailPage();
    const box = await screen.findByTestId("proctor-box");
    expect(within(box).queryByTestId("org-notice")).toBeNull();
  });

  it("the enrol button comes before the agenda in the focus order (it is first on screen on a phone)", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/workshops/runs/4/": detail() }) as typeof api);
    detailPage();
    const enrol = await screen.findByRole("button", { name: /enrol for free/i });
    const agenda = screen.getByRole("list", { name: "What you'll do" });
    expect(enrol.compareDocumentPosition(agenda) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(enrol.closest("aside")?.className).not.toMatch(/\border-/);
  });

  it("the lobby shows the same tracking box, with the institution line for org runs", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({ "/api/workshops/runs/4/": detail({ enrolled: true, my_status: "enrolled", audience: "org", proctoring: "off" }, 10) }) as typeof api);
    lobbyPage();
    const box = await screen.findByTestId("proctor-box");
    expect(within(box).getByTestId("proctor-notice")).toHaveTextContent(/No camera and no tab tracking/);
    expect(within(box).getByTestId("org-notice")).toHaveTextContent("Your institution can see your progress, answers, scores and help summaries during this workshop.");
    expect(box).toHaveTextContent("Never the camera or microphone recording.");
  });
});
