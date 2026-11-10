import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DialogHost } from "@/components/dialog";
import { ApiError, api } from "@/lib/api";
import { mergeTrace, type AgentConfig, type AgentRun } from "@/lib/workshops";

import { AgentBuilder } from "./AgentBuilder";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const SECRET = "sk-very-secret-123";
const B = "/api/workshops/sessions/7/agent/";

const tools = (on: string[] = []) =>
  ["calculator", "workshop_notes", "datetime", "units", "word_count"].map((name) => ({ name, description: `${name} desc`, enabled: on.includes(name) }));

const config = (over: Partial<AgentConfig> = {}): AgentConfig => ({
  name: "GST Helper", role: "You help with GST.", starter: "What is 18% GST on 2450?",
  aasan_tools: tools(["calculator"]), servers: [], auto_approve: {}, runs_left: 5,
  mcp: { url: "https://aasan.example/api/workshops/mcp/", token: "mcp-tok-abc", expires_at: "2026-10-19T10:00:00Z" },
  ...over,
});

type Init = { method?: string; json?: unknown };
let current: AgentConfig;
let routes: Record<string, (init?: Init) => unknown>;
const apiMock = vi.mocked(api);
const calls = (path: string) => apiMock.mock.calls.filter(([p]) => p === path);

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DialogHost />
      <AgentBuilder sessionId={7} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  current = config();
  routes = {
    [B]: (init) => {
      if (init?.method === "PUT") {
        const body = init.json as { name: string; role: string; starter: string; aasan_tools: string[] };
        current = { ...current, name: body.name, role: body.role, starter: body.starter, aasan_tools: tools(body.aasan_tools) };
      }
      return current;
    },
  };
  apiMock.mockImplementation((async (path: string, init?: Init) => {
    const fn = routes[path];
    if (!fn) throw new Error(`unmocked ${path}`);
    return fn(init);
  }) as typeof api);
});
afterEach(() => apiMock.mockReset());

describe("name, role and tools", () => {
  it("loads the agent, toggles a tool and saves the whole config", async () => {
    mount();
    const name = await screen.findByDisplayValue("GST Helper");
    fireEvent.change(name, { target: { value: "Shop Buddy" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /unit converter/i }));
    expect(screen.getByText(/aren't saved yet/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /save agent/i }));
    expect(await screen.findByText(/saved\. your agent is ready/i)).toBeInTheDocument();
    expect(calls(B).find(([, i]) => (i as Init)?.method === "PUT")?.[1]).toEqual({
      method: "PUT",
      json: { name: "Shop Buddy", role: "You help with GST.", starter: "What is 18% GST on 2450?", aasan_tools: ["calculator", "units"], enabled: {} },
    });
  });

  it("asks for a name before saving", async () => {
    mount();
    fireEvent.change(await screen.findByDisplayValue("GST Helper"), { target: { value: "  " } });
    fireEvent.click(screen.getByRole("button", { name: /save agent/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/give your agent a name/i);
    expect(calls(B).some(([, i]) => (i as Init)?.method === "PUT")).toBe(false);
  });

  it("stops at 8 tools in total across Aasan Tools and the learner's servers", async () => {
    current = config({
      aasan_tools: tools(["calculator", "workshop_notes", "datetime", "units"]),
      servers: [{ id: "s1", label: "Notes", url: "https://notes.example/mcp", has_token: false, status: "ok", tools: ["a", "b", "c", "d", "e"].map((n) => ({ name: n, description: "", enabled: ["a", "b", "c"].includes(n) })) }],
    });
    mount();
    expect(await screen.findByTestId("tool-count")).toHaveTextContent("7 of 8 tools on");
    fireEvent.click(screen.getByRole("checkbox", { name: /^d$/ }));
    expect(screen.getByTestId("tool-count")).toHaveTextContent("8 of 8 tools on");
    expect(screen.getByText(/most tools one agent can have/i)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /^e$/ })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /word count/i })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /^d$/ })).toBeEnabled(); // ticked ones can still be unticked
    fireEvent.click(screen.getByRole("checkbox", { name: /calculator/i }));
    expect(screen.getByRole("checkbox", { name: /^e$/ })).toBeEnabled();
  });
});

describe("connecting the learner's own MCP server", () => {
  it.each([
    ["blocked_host", /private or local network/i],
    ["unreachable", /couldn't reach that server/i],
    ["not_mcp", /didn't answer like an MCP server/i],
    ["auth_failed", /said no to the token/i],
    ["external_off", /switched off for your batch/i],
  ])("shows a calm message for %s", async (code, text) => {
    routes[`${B}servers/`] = () => {
      throw new ApiError(400, { code });
    };
    mount();
    fireEvent.change(await screen.findByLabelText(/server url \(https only\)/i), { target: { value: "https://10.0.0.1/mcp" } });
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("explains how the token is sent, including a custom header", async () => {
    mount();
    expect(await screen.findByText(/sent as “Authorization: Bearer …”/)).toHaveTextContent("X-Api-Key: value");
  });

  it("refuses a plain http address before sending anything", async () => {
    mount();
    fireEvent.change(await screen.findByLabelText(/server url \(https only\)/i), { target: { value: "http://example.com/mcp" } });
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/must start with https/i);
    expect(calls(`${B}servers/`)).toHaveLength(0);
  });

  it("sends the token once, then never shows it again", async () => {
    routes[`${B}servers/`] = () => {
      current = { ...current, servers: [{ id: 3, label: "My tools", url: "https://tools.example/mcp", has_token: true, status: "ok", tools: [{ name: "lookup_order", description: "Find an order", enabled: false }] }] };
      return current.servers[0];
    };
    const { container } = mount();
    fireEvent.change(await screen.findByLabelText(/server url \(https only\)/i), { target: { value: "https://tools.example/mcp" } });
    fireEvent.change(screen.getByLabelText(/name for this server/i), { target: { value: "My tools" } });
    const token = screen.getByLabelText(/token or api key/i);
    expect(token).toHaveAttribute("type", "password");
    fireEvent.change(token, { target: { value: SECRET } });
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(await screen.findByTestId("token-saved")).toHaveTextContent("Token •••• saved");
    expect(calls(`${B}servers/`)[0][1]).toEqual({ method: "POST", json: { url: "https://tools.example/mcp", label: "My tools", token: SECRET } });
    expect(screen.getByLabelText(/token or api key/i)).toHaveValue("");
    expect(container.innerHTML).not.toContain(SECRET);
    expect(screen.getByRole("checkbox", { name: /lookup_order/i })).not.toBeChecked();
    expect(screen.getByText(/aasan asks you before running each one/i)).toBeInTheDocument();
  });

  it("removes a server after confirming, and hides the form at 3 servers", async () => {
    const server = (id: number) => ({ id, label: `S${id}`, url: `https://s${id}.example/mcp`, has_token: false, status: "ok", tools: [] });
    current = config({ servers: [server(1), server(2), server(3)] });
    routes[`${B}servers/2/`] = () => {
      current = { ...current, servers: [server(1), server(3)] };
      return null;
    };
    mount();
    expect(await screen.findByText(/connected 3 servers/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^connect$/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /remove: S2/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /^remove$/i }));
    await waitFor(() => expect(screen.getAllByTestId("mcp-server")).toHaveLength(2));
    expect(calls(`${B}servers/2/`)[0][1]).toEqual({ method: "DELETE" });
    expect(screen.getByRole("button", { name: /^connect$/i })).toBeInTheDocument();
  });
});

describe("test chat", () => {
  const ext = { id: "s1", label: "My tools", url: "https://tools.example/mcp", has_token: true, status: "ok", tools: [{ name: "lookup_order", description: "", enabled: true }] };

  it("renders each step of the trace, with tool output as plain text", async () => {
    routes[`${B}run/`] = (): AgentRun => ({
      done: true, runs_left: 4,
      trace: [
        { type: "thought", text: "I should use the calculator." },
        { type: "tool_call", tool: "calculator", server: "Aasan", arguments: { expression: "2450*0.18" } },
        { type: "error", code: "too_many_tool_calls" },
        { type: "tool_result", tool: "calculator", text: "<img src=x onerror=alert(1)><b>441</b>", truncated: true },
        { type: "answer", text: "18% GST on ₹2,450 is ₹441." },
      ],
    });
    const { container } = mount();
    expect(await screen.findByTestId("runs-left")).toHaveTextContent("5 test messages left");
    fireEvent.change(screen.getByPlaceholderText(/ask your agent something/i), { target: { value: "GST on 2450?" } });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    expect(await screen.findByTestId("trace-answer")).toHaveTextContent("₹441");
    expect(screen.getByText("I should use the calculator.")).toBeInTheDocument();
    const call = screen.getByTestId("trace-tool-call");
    expect(call).toHaveTextContent("Uses calculator");
    expect(call).toHaveTextContent("Aasan tool");
    expect(call).toHaveTextContent('"expression": "2450*0.18"');
    const result = screen.getByTestId("trace-tool-result");
    expect(result).toHaveTextContent("What calculator sent back (shortened)");
    expect(result).toHaveTextContent("<img src=x onerror=alert(1)><b>441</b>");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull(); // the informational too_many_tool_calls step stays quiet
    expect(screen.getByTestId("runs-left")).toHaveTextContent("4 test messages left");
    expect(calls(`${B}run/`)[0][1]).toEqual({ method: "POST", json: { message: "GST on 2450?" } });
  });

  it("saves unsaved changes before a test run", async () => {
    routes[`${B}run/`] = (): AgentRun => ({ done: true, trace: [{ type: "answer", text: "Hi" }] });
    mount();
    fireEvent.change(await screen.findByDisplayValue("GST Helper"), { target: { value: "New name" } });
    fireEvent.click(screen.getByRole("button", { name: /try your first message/i }));
    await screen.findByTestId("trace-answer");
    const order = apiMock.mock.calls.map(([p, i]) => `${(i as Init)?.method ?? "GET"} ${p}`);
    expect(order.indexOf(`PUT ${B}`)).toBeGreaterThan(-1);
    expect(order.indexOf(`PUT ${B}`)).toBeLessThan(order.indexOf(`POST ${B}run/`));
    expect(screen.getByTestId("runs-left")).toHaveTextContent("4 test messages left"); // counted down locally
  });

  it("asks before running the learner's own server tool, then continues on Approve", async () => {
    current = config({ servers: [ext] });
    const pending = { call_id: "c1", server: "My tools", tool: "lookup_order", arguments: { id: 42 } };
    routes[`${B}run/`] = (): AgentRun => ({
      done: false, pending,
      trace: [{ type: "tool_call", name: "ext_1__lookup_order", server: "My tools", arguments: { id: 42 } }, { type: "approval_needed", ...pending }],
    });
    routes[`${B}approve/`] = (): AgentRun => ({ done: true, trace: [{ type: "tool_result", name: "ext_1__lookup_order", result: { status: "shipped" } }, { type: "answer", text: "Order 42 has shipped." }] });
    mount();
    fireEvent.change(await screen.findByPlaceholderText(/ask your agent something/i), { target: { value: "Where is order 42?" } });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    const card = await screen.findByTestId("approval-card");
    expect(card).toHaveTextContent("Your agent wants to use lookup_order on My tools");
    expect(card).toHaveTextContent('"id": 42');
    expect(screen.getByTestId("trace-tool-call")).toHaveTextContent("Your server: My tools");
    expect(screen.getByRole("button", { name: /^send$/i })).toBeDisabled();
    fireEvent.click(within(card).getByRole("button", { name: /^approve$/i }));
    expect(await screen.findByTestId("trace-answer")).toHaveTextContent("Order 42 has shipped.");
    expect(screen.queryByTestId("approval-card")).toBeNull();
    expect(screen.getByTestId("approval-done")).toHaveTextContent("You allowed lookup_order to run.");
    expect(screen.getByTestId("trace-tool-call")).toBeInTheDocument(); // the earlier steps stay
    expect(calls(`${B}approve/`)[0][1]).toEqual({ method: "POST", json: { call_id: "c1", decision: "approve" } });
  });

  it.each([
    ["deny", /^deny$/i, "You said no — lookup_order didn't run."],
    ["always", /always allow for this session/i, "lookup_order is always allowed for this session."],
  ])("records %s", async (decision, button, line) => {
    current = config({ servers: [ext] });
    const pending = { call_id: "c9", server: "My tools", tool: "lookup_order", arguments: {} };
    routes[`${B}run/`] = (): AgentRun => ({ done: false, pending, trace: [{ type: "approval_needed", ...pending }] });
    routes[`${B}approve/`] = (init): AgentRun => {
      if ((init!.json as { decision: string }).decision === "always") current = { ...current, auto_approve: { s1: ["lookup_order"] } };
      return { done: true, trace: [{ type: "approval_needed", ...pending }, { type: "answer", text: "Done." }] };
    };
    mount();
    fireEvent.change(await screen.findByPlaceholderText(/ask your agent something/i), { target: { value: "Go" } });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    fireEvent.click(within(await screen.findByTestId("approval-card")).getByRole("button", { name: button }));
    expect(await screen.findByTestId("approval-done")).toHaveTextContent(line);
    expect(screen.getAllByTestId("trace-answer")).toHaveLength(1); // a full re-sent trace isn't duplicated
    expect(calls(`${B}approve/`)[0][1]).toEqual({ method: "POST", json: { call_id: "c9", decision } });
    if (decision === "always") expect(await screen.findByText("Always allowed")).toBeInTheDocument();
  });

  it("restores the saved chat and a run still waiting for approval after a reload", async () => {
    current = config({
      servers: [ext],
      chat: [{ role: "user", text: "Hello agent" }, { role: "agent", text: "Hello! How can I help?" }],
      pending: { call_id: "c5", server: "My tools", tool: "lookup_order", arguments: { id: 7 } },
    });
    routes[`${B}approve/`] = (): AgentRun => ({ done: true, trace: [{ type: "answer", text: "Order 7 is packed." }] });
    mount();
    expect(await screen.findByText("Hello agent")).toBeInTheDocument();
    expect(screen.getByText("Hello! How can I help?")).toBeInTheDocument();
    const card = screen.getByTestId("approval-card");
    expect(card).toHaveTextContent('"id": 7');
    fireEvent.click(within(card).getByRole("button", { name: /^deny$/i }));
    expect(await screen.findByText("Order 7 is packed.")).toBeInTheDocument();
    expect(calls(`${B}approve/`)[0][1]).toEqual({ method: "POST", json: { call_id: "c5", decision: "deny" } });
  });

  it.each([
    ["session_submitted", /already submitted/i],
    ["bad_call", /tool request wasn't valid/i],
    ["no_pending", /already been answered/i],
    ["rate_limited", /a lot of messages at once/i],
  ])("explains a %s refusal", async (code, text) => {
    routes[`${B}run/`] = () => {
      throw new ApiError(409, { code });
    };
    mount();
    fireEvent.change(await screen.findByPlaceholderText(/ask your agent something/i), { target: { value: "Hi" } });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("shows when the test messages are used up", async () => {
    current = config({ runs_left: 1 });
    routes[`${B}run/`] = () => {
      throw new ApiError(429, { code: "runs_exhausted" });
    };
    mount();
    expect(await screen.findByTestId("runs-left")).toHaveTextContent("1 test message left");
    fireEvent.change(screen.getByPlaceholderText(/ask your agent something/i), { target: { value: "Hi" } });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/used all the test messages/i);
    expect(screen.getByTestId("runs-left")).toHaveTextContent(/used all the test messages/i);
    expect(screen.getByPlaceholderText(/ask your agent something/i)).toBeDisabled();
  });
});

describe("Aasan Tools for the learner's own MCP client", () => {
  it("masks the token until asked, with copy buttons and the expiry", async () => {
    const write = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText: write }, configurable: true });
    mount();
    const card = await screen.findByTestId("mcp-card");
    expect(card).toHaveTextContent("https://aasan.example/api/workshops/mcp/");
    expect(screen.getByTestId("mcp-token")).not.toHaveTextContent("mcp-tok-abc");
    expect(card).toHaveTextContent(/until you submit the final/i);
    fireEvent.click(within(card).getByRole("button", { name: /copy: access token/i }));
    expect(write).toHaveBeenCalledWith("mcp-tok-abc");
    fireEvent.click(within(card).getByRole("button", { name: /^show$/i }));
    expect(screen.getByTestId("mcp-token")).toHaveTextContent("mcp-tok-abc");
  });
});

describe("mergeTrace", () => {
  it("replaces when the server re-sends the whole trace and appends new steps otherwise", () => {
    const a = [{ type: "thought" as const, text: "x" }];
    const full = [...a, { type: "answer" as const, text: "y" }];
    expect(mergeTrace(a, full)).toEqual(full);
    expect(mergeTrace(a, [{ type: "answer", text: "y" }])).toEqual(full);
  });
});
