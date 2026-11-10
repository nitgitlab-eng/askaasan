import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, Copy, Eye, EyeOff, Lightbulb, Plug, RefreshCw, RotateCcw, Save, Send, ShieldCheck, Trash2, Wrench } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import { confirmDialog } from "@/lib/dialog";
import {
  AGENT_MAX_SERVERS, AGENT_MAX_TOOLS, AGENT_MESSAGE_MAX, AGENT_NAME_MAX, AGENT_ROLE_MAX, AGENT_STARTER_MAX,
  asText, enabledToolCount, errorCode, mergeTrace, workshops,
  type AgentConfig, type AgentRun, type AgentSave, type AgentServer, type ApprovalDecision, type PendingCall, type TraceStep,
} from "@/lib/workshops";

const agentKey = (id: number) => ["workshop-agent", id] as const;

const AASAN_TOOLS = ["calculator", "workshop_notes", "datetime", "units", "word_count"];
const OK_STATUS = new Set(["ok", "connected", "ready"]);

type Draft = AgentSave;

const fromConfig = (c: AgentConfig): Draft => ({
  name: c.name ?? "",
  role: c.role ?? "",
  starter: c.starter ?? "",
  aasan_tools: c.aasan_tools.filter((x) => x.enabled).map((x) => x.name),
  enabled: Object.fromEntries(c.servers.map((s) => [String(s.id), s.tools.filter((x) => x.enabled).map((x) => x.name)])),
});

/** After a refetch (server added, refreshed or removed): keep the learner's unsaved edits, follow the server list. */
function reconcile(d: Draft, c: AgentConfig): Draft {
  const fresh = fromConfig(c);
  const enabled = Object.fromEntries(
    c.servers.map((s) => {
      const key = String(s.id);
      const names = new Set(s.tools.map((x) => x.name));
      return [key, key in d.enabled ? d.enabled[key].filter((n) => names.has(n)) : fresh.enabled[key]];
    }),
  );
  return { ...d, enabled };
}

/** A few server codes share one message. */
const ALIAS: Record<string, string> = { runs_exhausted: "no_runs_left", cap: "budget", unknown_server: "bad_tool", session_expired: "unreachable" };
const codeOf = (e: unknown) => {
  const c = errorCode(e);
  return ALIAS[c] ?? c;
};
/** Informational only: the server kept the first few calls and carried on. */
const QUIET_ERRORS = new Set(["too_many_tool_calls"]);

const sameDraft = (a: Draft, b: Draft) => JSON.stringify(a) === JSON.stringify(b);

/** External tools come back namespaced as ext_<n>__<tool>; show the learner the tool's own name. */
function toolLabel(step: TraceStep): { tool: string; external: boolean } {
  const raw = step.name ?? step.tool ?? "";
  const m = /^ext_\d+__(.+)$/.exec(raw);
  const external = !!m || (!!step.server && step.server.toLowerCase() !== "aasan");
  return { tool: m ? m[1] : raw, external };
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  return (
    <Button type="button" variant="outline" className="shrink-0 px-3 py-1.5 text-sm" aria-label={`${t("workshop.agent.copy")}: ${label}`}
      onClick={() => {
        void navigator.clipboard?.writeText(value).catch(() => undefined);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}>
      {copied ? <Check className="h-4 w-4 text-good" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />} {copied ? t("workshop.agent.copied") : t("workshop.agent.copy")}
    </Button>
  );
}

function StepHeading({ n, title, sub }: { n: number; title: string; sub?: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent text-sm font-bold text-accent-ink" aria-hidden>{n}</span>
      <div className="min-w-0">
        <h3 className="font-display text-lg font-bold">{title}</h3>
        {sub && <p className="text-sm text-muted">{sub}</p>}
      </div>
    </div>
  );
}

function ToolRow({ name, title, description, checked, disabled, badge, onChange }: { name: string; title: string; description: string; checked: boolean; disabled: boolean; badge?: string; onChange: (v: boolean) => void }) {
  return (
    <li>
      <label className={cn("flex items-start gap-3 rounded-xl border-2 px-3 py-2.5 transition", checked ? "border-accent/50 bg-accent/5" : "border-line", disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:border-accent")}>
        <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="mt-1 h-5 w-5 shrink-0 accent-[var(--accent)]" data-tool={name} />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2 font-semibold">
            <span className="break-all">{title}</span>
            {badge && <span className="rounded-full bg-good/15 px-2 py-0.5 text-xs font-semibold text-good">{badge}</span>}
          </span>
          {description && <span className="block break-words text-sm text-muted">{description}</span>}
        </span>
      </label>
    </li>
  );
}

function ServerCard({ sessionId, server, draft, full, autoApproved, onToggle, onChanged }: {
  sessionId: number; server: AgentServer; draft: string[]; full: boolean; autoApproved: string[];
  onToggle: (tool: string, on: boolean) => void; onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState<"refresh" | "remove" | null>(null);
  const [problem, setProblem] = useState("");
  const ok = OK_STATUS.has(server.status);
  const label = server.label || server.url;

  async function act(kind: "refresh" | "remove") {
    if (kind === "remove" && !(await confirmDialog(t("workshop.agent.removeConfirm", { name: label }), { danger: true, ok: t("workshop.agent.remove") }))) return;
    setBusy(kind);
    setProblem("");
    try {
      if (kind === "refresh") await workshops.refreshServer(sessionId, server.id);
      else await workshops.removeServer(sessionId, server.id);
      onChanged();
    } catch (e) {
      setProblem(t(`workshop.agent.err.${codeOf(e)}`, { defaultValue: t("workshop.agent.err.generic") }));
    } finally {
      setBusy(null);
    }
  }

  return (
    <li className="space-y-3 rounded-2xl border-2 border-line p-3" data-testid="mcp-server">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="break-words font-semibold">{label}</p>
          {server.label && <p className="break-all text-xs text-muted">{server.url}</p>}
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm">
            <span className={cn("inline-flex items-center gap-1.5 font-medium", ok ? "text-good" : "text-bad")}>
              <span className={cn("h-2 w-2 rounded-full", ok ? "bg-good" : "bg-bad")} aria-hidden />
              {ok ? t("workshop.agent.connected") : t("workshop.agent.notConnected")}
            </span>
            {server.has_token && <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-muted" data-testid="token-saved">{t("workshop.agent.tokenSaved")}</span>}
          </p>
        </div>
        <div className="flex gap-1">
          <Button type="button" variant="ghost" className="px-2.5 py-1.5 text-sm" loading={busy === "refresh"} disabled={!!busy} onClick={() => void act("refresh")} aria-label={`${t("workshop.agent.refresh")}: ${label}`}>
            <RefreshCw className="h-4 w-4" aria-hidden /> <span className="hidden sm:inline">{t("workshop.agent.refresh")}</span>
          </Button>
          <Button type="button" variant="ghost" className="px-2.5 py-1.5 text-sm text-bad" loading={busy === "remove"} disabled={!!busy} onClick={() => void act("remove")} aria-label={`${t("workshop.agent.remove")}: ${label}`}>
            <Trash2 className="h-4 w-4" aria-hidden /> <span className="hidden sm:inline">{t("workshop.agent.remove")}</span>
          </Button>
        </div>
      </div>
      {!ok && server.error && <p role="alert" className="text-sm text-bad">{t(`workshop.agent.err.${ALIAS[server.error] ?? server.error}`, { defaultValue: t("workshop.agent.err.generic") })}</p>}
      {problem && <p role="alert" className="text-sm text-bad">{problem}</p>}
      {ok && !server.tools.length && <p className="text-sm text-muted">{t("workshop.agent.noTools")}</p>}
      {!!server.tools.length && (
        <ul className="space-y-2" aria-label={t("workshop.agent.serverTools", { name: label })}>
          {server.tools.map((x) => {
            const on = draft.includes(x.name);
            return (
              <ToolRow key={x.name} name={x.name} title={x.name} description={x.description} checked={on} disabled={!on && full}
                badge={autoApproved.includes(x.name) ? t("workshop.agent.alwaysAllowed") : undefined} onChange={(v) => onToggle(x.name, v)} />
            );
          })}
        </ul>
      )}
    </li>
  );
}

function ConnectForm({ sessionId, onConnected }: { sessionId: number; onConnected: () => void }) {
  const { t } = useTranslation();
  const [url, setUrl] = useState("");
  const [label, setLabel] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    const u = url.trim();
    if (!u) return setProblem(t("workshop.agent.err.bad_url"));
    if (!/^https:\/\//i.test(u)) return setProblem(t("workshop.agent.err.not_https"));
    setBusy(true);
    setProblem("");
    try {
      await workshops.addServer(sessionId, { url: u, ...(label.trim() ? { label: label.trim() } : {}), ...(token ? { token } : {}) });
      // The token now lives only on the server (encrypted); drop every copy on this side.
      setUrl("");
      setLabel("");
      setToken("");
      onConnected();
    } catch (err) {
      setToken("");
      setProblem(t(`workshop.agent.err.${codeOf(err)}`, { defaultValue: t("workshop.agent.err.generic") }));
    } finally {
      setBusy(false);
    }
  }

  const input = "mt-1 w-full rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent";
  return (
    <form onSubmit={submit} className="space-y-3 rounded-2xl bg-surface-2 p-3" aria-label={t("workshop.agent.connectTitle")}>
      <p className="font-semibold">{t("workshop.agent.connectTitle")}</p>
      <label className="block">
        <span className="text-sm font-medium">{t("workshop.agent.url")}</span>
        <input type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/mcp" maxLength={500} autoComplete="off" spellCheck={false} className={input} />
      </label>
      <label className="block">
        <span className="text-sm font-medium">{t("workshop.agent.label")}</span>
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t("workshop.agent.labelPh")} maxLength={60} className={input} />
      </label>
      <label className="block">
        <span className="text-sm font-medium">{t("workshop.agent.token")}</span>
        <input type="password" value={token} onChange={(e) => setToken(e.target.value)} maxLength={2000} autoComplete="new-password" spellCheck={false} className={input} />
        <span className="mt-1 block text-xs text-muted">{t("workshop.agent.tokenHint")}</span>
        <span className="mt-1 block text-xs text-muted">{t("workshop.agent.tokenHeader")}</span>
      </label>
      {problem && <p role="alert" className="text-sm text-bad">{problem}</p>}
      <Button type="submit" loading={busy} className="w-full sm:w-auto"><Plug className="h-4 w-4" aria-hidden /> {busy ? t("workshop.agent.connecting") : t("workshop.agent.connect")}</Button>
    </form>
  );
}

function McpCard({ mcp }: { mcp: AgentConfig["mcp"] }) {
  const { t, i18n } = useTranslation();
  const [show, setShow] = useState(false);
  if (!mcp) return null;
  const expires = new Date(mcp.expires_at);
  const when = Number.isNaN(expires.getTime()) ? mcp.expires_at : expires.toLocaleString(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  return (
    <Card className="space-y-3" data-testid="mcp-card">
      <div>
        <h3 className="flex items-center gap-2 font-display text-lg font-bold"><Plug className="h-5 w-5 text-accent" aria-hidden /> {t("workshop.agent.mcpTitle")}</h3>
        <p className="text-sm text-muted">{t("workshop.agent.mcpSub")}</p>
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">{t("workshop.agent.mcpUrl")}</p>
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 break-all rounded-lg bg-surface-2 px-2 py-1.5 text-sm">{mcp.url}</code>
          <CopyButton value={mcp.url} label={t("workshop.agent.mcpUrl")} />
        </div>
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">{t("workshop.agent.mcpToken")}</p>
        <div className="flex flex-wrap items-center gap-2">
          <code className="min-w-0 flex-1 break-all rounded-lg bg-surface-2 px-2 py-1.5 text-sm" data-testid="mcp-token">{show ? mcp.token : "••••••••••••"}</code>
          <div className="flex gap-2">
            <Button type="button" variant="outline" className="px-3 py-1.5 text-sm" aria-pressed={show} onClick={() => setShow((v) => !v)}>
              {show ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />} {show ? t("workshop.agent.hide") : t("workshop.agent.show")}
            </Button>
            <CopyButton value={mcp.token} label={t("workshop.agent.mcpToken")} />
          </div>
        </div>
      </div>
      <p className="text-sm text-muted">{t("workshop.agent.mcpExpires", { time: when })}</p>
      <p className="text-sm">{t("workshop.agent.mcpHow")}</p>
    </Card>
  );
}

function ToolCallChip({ step }: { step: TraceStep }) {
  const { t } = useTranslation();
  const { tool, external } = toolLabel(step);
  const args = asText(step.arguments);
  return (
    <div className="space-y-1.5 rounded-xl border-2 border-accent/30 p-2.5" data-testid="trace-tool-call">
      <p className="flex flex-wrap items-center gap-2 text-sm">
        <span className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-accent/15 px-2.5 py-0.5 font-semibold text-ink"><Wrench className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden /> <span className="min-w-0 [overflow-wrap:anywhere]">{t("workshop.agent.trace.call", { tool })}</span></span>
        <span className="[overflow-wrap:anywhere] text-xs text-muted">{external ? t("workshop.agent.trace.yourServer", { server: step.server || "" }) : t("workshop.agent.trace.aasanTool")}</span>
      </p>
      {args && args !== "{}" && (
        <div>
          <p className="text-xs font-semibold text-muted">{t("workshop.agent.trace.args")}</p>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface-2 p-2 text-xs"><code>{args}</code></pre>
        </div>
      )}
    </div>
  );
}

function ToolResult({ step }: { step: TraceStep }) {
  const { t } = useTranslation();
  const { tool } = toolLabel(step);
  const body = asText(step.result ?? step.text);
  return (
    <details className="rounded-xl bg-surface-2 p-2.5" data-testid="trace-tool-result">
      <summary className="cursor-pointer [overflow-wrap:anywhere] text-sm font-semibold">
        {t("workshop.agent.trace.result", { tool })}{step.truncated ? ` ${t("workshop.agent.trace.truncated")}` : ""}
      </summary>
      {/* Tool output is untrusted: shown as plain text, never as markup or links. */}
      <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs"><code>{body}</code></pre>
    </details>
  );
}

function ApprovalCard({ pending, busy, onDecide }: { pending: PendingCall; busy: ApprovalDecision | null; onDecide: (d: ApprovalDecision) => void }) {
  const { t } = useTranslation();
  return (
    <div role="group" aria-labelledby={`approve-${pending.call_id}`} className="space-y-3 rounded-2xl border-2 border-accent bg-accent/5 p-3" data-testid="approval-card">
      <p id={`approve-${pending.call_id}`} className="flex items-center gap-2 font-semibold"><ShieldCheck className="h-5 w-5 shrink-0 text-accent" aria-hidden /> {t("workshop.agent.approval.title")}</p>
      <p className="break-words text-sm [overflow-wrap:anywhere]">{t("workshop.agent.approval.body", { tool: pending.tool, server: pending.server })}</p>
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface p-2 text-xs"><code>{asText(pending.arguments) || "{}"}</code></pre>
      <div className="flex flex-wrap gap-2">
        <Button type="button" loading={busy === "approve"} disabled={!!busy} onClick={() => onDecide("approve")}>{t("workshop.agent.approval.approve")}</Button>
        <Button type="button" variant="outline" loading={busy === "deny"} disabled={!!busy} onClick={() => onDecide("deny")}>{t("workshop.agent.approval.deny")}</Button>
        <Button type="button" variant="ghost" loading={busy === "always"} disabled={!!busy} onClick={() => onDecide("always")}>{t("workshop.agent.approval.always")}</Button>
      </div>
    </div>
  );
}

interface ChatTurn { id: number; message: string; trace: TraceStep[]; pending: PendingCall | null; decisions: Record<string, ApprovalDecision> }

function Trace({ turn, busy, onDecide }: { turn: ChatTurn; busy: ApprovalDecision | null; onDecide: (d: ApprovalDecision) => void }) {
  const { t } = useTranslation();
  return (
    <ol className="space-y-2" aria-label={t("workshop.agent.trace.label")}>
      {turn.trace.map((step, i) => {
        let node: ReactNode = null;
        switch (step.type) {
          case "thought":
            node = <p className="flex gap-2 text-sm italic text-muted"><Lightbulb className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /><span className="min-w-0 whitespace-pre-wrap break-words"><span className="sr-only">{t("workshop.agent.trace.thought")}: </span>{step.text}</span></p>;
            break;
          case "tool_call":
            node = <ToolCallChip step={step} />;
            break;
          case "tool_result":
            node = <ToolResult step={step} />;
            break;
          case "approval_needed": {
            if (turn.pending && step.call_id === turn.pending.call_id) break; // shown as the live card below
            const d = step.call_id ? turn.decisions[step.call_id] : undefined;
            if (d) node = <p className="text-sm text-muted" data-testid="approval-done">{t(`workshop.agent.trace.${d === "deny" ? "denied" : d === "always" ? "always" : "approved"}`, { tool: step.tool ?? step.name ?? "" })}</p>;
            break;
          }
          case "answer":
            node = (
              <div className="rounded-2xl bg-accent/10 p-3" data-testid="trace-answer">
                <p className="flex items-center gap-1.5 text-xs font-semibold text-accent"><Bot className="h-4 w-4" aria-hidden /> {t("workshop.agent.trace.answer")}</p>
                <p className="whitespace-pre-wrap break-words">{step.text}</p>
              </div>
            );
            break;
          case "error":
            if (QUIET_ERRORS.has(step.code ?? "")) break;
            node = <p role="alert" className="text-sm text-bad">{t(`workshop.agent.runErr.${ALIAS[step.code ?? ""] ?? step.code ?? ""}`, { defaultValue: t("workshop.agent.trace.error") })}</p>;
            break;
        }
        return node && <li key={i}>{node}</li>;
      })}
      {turn.pending && <li><ApprovalCard pending={turn.pending} busy={busy} onDecide={onDecide} /></li>}
    </ol>
  );
}

/** The saved test conversation (and a run still waiting for approval) from the server, so a reload picks up where it was. */
function restore(chat: AgentConfig["chat"], pending: AgentConfig["pending"]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  for (const m of chat ?? []) {
    if (m.role === "user") turns.push({ id: turns.length + 1, message: m.text, trace: [], pending: null, decisions: {} });
    else if (turns.length) turns[turns.length - 1].trace.push({ type: "answer", text: m.text });
  }
  if (pending?.call_id) turns.push({ id: turns.length + 1, message: "", trace: [], pending, decisions: {} });
  return turns;
}

function TestChat({ sessionId, runsLeft, setRunsLeft, beforeRun, starter, onAlways, initial }: {
  sessionId: number; runsLeft: number; setRunsLeft: (n: number) => void; beforeRun: () => Promise<boolean>; starter: string; onAlways: () => void; initial: ChatTurn[];
}) {
  const { t } = useTranslation();
  const [turns, setTurns] = useState<ChatTurn[]>(initial);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [deciding, setDeciding] = useState<ApprovalDecision | null>(null);
  const [problem, setProblem] = useState("");
  const out = runsLeft <= 0;
  const waiting = turns.some((x) => x.pending);

  const apply = (id: number, r: AgentRun, decision?: { call: string; d: ApprovalDecision }) => {
    setTurns((all) => all.map((x) => (x.id === id ? {
      ...x,
      trace: decision ? mergeTrace(x.trace, r.trace ?? []) : r.trace ?? [],
      pending: r.done ? null : r.pending ?? null,
      decisions: decision ? { ...x.decisions, [decision.call]: decision.d } : x.decisions,
    } : x)));
    if (typeof r.runs_left === "number") setRunsLeft(r.runs_left);
  };

  async function send(message: string) {
    const msg = message.trim();
    if (!msg || busy || out || waiting) return;
    setProblem("");
    setBusy(true);
    try {
      if (!(await beforeRun())) return;
      const r = await workshops.runAgent(sessionId, msg);
      const id = Date.now();
      setTurns((all) => [...all, { id, message: msg, trace: [], pending: null, decisions: {} }]);
      apply(id, r);
      if (typeof r.runs_left !== "number") setRunsLeft(Math.max(0, runsLeft - 1));
      setText("");
    } catch (e) {
      const code = codeOf(e);
      if (code === "no_runs_left") setRunsLeft(0);
      setProblem(t(`workshop.agent.runErr.${code}`, { defaultValue: t("workshop.agent.runErr.generic") }));
    } finally {
      setBusy(false);
    }
  }

  async function decide(turn: ChatTurn, d: ApprovalDecision) {
    if (!turn.pending) return;
    setDeciding(d);
    setProblem("");
    try {
      const r = await workshops.approve(sessionId, turn.pending.call_id, d);
      apply(turn.id, r, { call: turn.pending.call_id, d });
      if (d === "always") onAlways();
    } catch (e) {
      setProblem(t(`workshop.agent.runErr.${codeOf(e)}`, { defaultValue: t("workshop.agent.runErr.generic") }));
    } finally {
      setDeciding(null);
    }
  }

  async function reset() {
    if (!(await confirmDialog(t("workshop.agent.resetConfirm"), { ok: t("workshop.agent.reset") }))) return;
    setProblem("");
    try {
      await workshops.resetAgent(sessionId);
      setTurns([]);
    } catch (e) {
      setProblem(t(`workshop.agent.runErr.${codeOf(e)}`, { defaultValue: t("workshop.agent.runErr.generic") }));
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={cn("text-sm font-semibold", out ? "text-bad" : "text-accent")} data-testid="runs-left">
          {out ? t("workshop.agent.noRuns") : t("workshop.agent.runsLeft", { count: runsLeft })}
        </p>
        {!!turns.length && (
          <Button type="button" variant="ghost" className="px-2.5 py-1.5 text-sm" onClick={() => void reset()} disabled={busy || !!deciding}>
            <RotateCcw className="h-4 w-4" aria-hidden /> {t("workshop.agent.reset")}
          </Button>
        )}
      </div>
      <div className="max-h-[32rem] space-y-4 overflow-y-auto" aria-live="polite">
        {!turns.length && <p className="rounded-xl bg-surface-2 px-3 py-2.5 text-sm text-muted">{t("workshop.agent.chatEmpty")}</p>}
        {turns.map((turn) => (
          <div key={turn.id} className="space-y-2">
            {turn.message && (
              <div className="ml-auto w-fit max-w-[85%] rounded-2xl bg-accent px-3 py-2 text-accent-ink">
                <p className="sr-only">{t("workshop.you")}:</p>
                <p className="whitespace-pre-wrap break-words">{turn.message}</p>
              </div>
            )}
            <Trace turn={turn} busy={deciding} onDecide={(d) => void decide(turn, d)} />
          </div>
        ))}
        {busy && <p role="status" className="text-sm text-muted">{t("workshop.agent.working")}</p>}
      </div>
      {problem && <p role="alert" className="text-sm text-bad">{problem}</p>}
      {waiting && <p className="text-sm text-muted">{t("workshop.agent.decideFirst")}</p>}
      <form className="flex flex-col gap-2 sm:flex-row" onSubmit={(e) => { e.preventDefault(); void send(text); }}>
        <label className="sr-only" htmlFor={`agent-msg-${sessionId}`}>{t("workshop.agent.msgPh")}</label>
        <input id={`agent-msg-${sessionId}`} value={text} onChange={(e) => setText(e.target.value)} maxLength={AGENT_MESSAGE_MAX} placeholder={t("workshop.agent.msgPh")} disabled={out}
          className="min-w-0 flex-1 rounded-xl border-2 border-line bg-surface px-3 py-2.5 outline-none focus:border-accent" />
        <Button type="submit" loading={busy} disabled={out || waiting || !text.trim()}><Send className="h-4 w-4" aria-hidden /> {t("workshop.agent.send")}</Button>
      </form>
      {starter.trim() && !turns.length && !out && (
        <button type="button" onClick={() => void send(starter)} disabled={busy} className="text-sm font-semibold text-accent hover:underline disabled:opacity-60">
          {t("workshop.agent.useStarter")}
        </button>
      )}
    </div>
  );
}

/**
 * The agent builder: name and job, Aasan Tools, the learner's own MCP servers, a step-by-step test chat and Save.
 * Everything a tool or the model returns is shown as plain text. A learner's server token is sent once and never shown again.
 */
export function AgentBuilder({ sessionId }: { sessionId: number }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data, error, refetch } = useQuery({ queryKey: agentKey(sessionId), queryFn: () => workshops.agent(sessionId) });
  const [seen, setSeen] = useState<AgentConfig | undefined>(undefined);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [runsLeft, setRunsLeft] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // Follow the server's copy without losing unsaved edits (adjusting state during render, not in an effect).
  if (data && data !== seen) {
    setSeen(data);
    setDraft((d) => (d ? reconcile(d, data) : fromConfig(data)));
    // Only a changed server count overrides the local one (a save or refetch mid-run must not undo the countdown).
    if (data.runs_left !== seen?.runs_left) setRunsLeft(data.runs_left);
  }

  if (error && !data) {
    return (
      <Card className="space-y-2">
        <p role="alert" className="text-bad">{t("workshop.agent.loadFailed")}</p>
        <Button variant="outline" onClick={() => void refetch()}>{t("workshop.agent.retry")}</Button>
      </Card>
    );
  }
  if (!data || !draft) return <Card><p className="text-muted">{t("workshop.agent.loading")}</p></Card>;

  const saved = fromConfig(data);
  const dirty = !sameDraft(draft, saved);
  const count = enabledToolCount(draft.aasan_tools, draft.enabled);
  const full = count >= AGENT_MAX_TOOLS;
  const reload = () => void qc.invalidateQueries({ queryKey: agentKey(sessionId) });
  const set = (patch: Partial<Draft>) => {
    setSaveMsg(null);
    setDraft((d) => (d ? { ...d, ...patch } : d));
  };
  const toggle = (list: string[], name: string, on: boolean) => (on ? (list.includes(name) || full ? list : [...list, name]) : list.filter((x) => x !== name));

  async function save(): Promise<boolean> {
    if (!draft) return false;
    if (!draft.name.trim()) {
      setSaveMsg({ ok: false, text: t("workshop.agent.needName") });
      return false;
    }
    setSaving(true);
    setSaveMsg(null);
    try {
      const body = { ...draft, name: draft.name.trim() };
      const out = await workshops.saveAgent(sessionId, body);
      if (out && Array.isArray(out.aasan_tools)) qc.setQueryData(agentKey(sessionId), out);
      else reload();
      setSaveMsg({ ok: true, text: t("workshop.agent.saved") });
      return true;
    } catch (e) {
      setSaveMsg({ ok: false, text: t(`workshop.agent.saveErr.${codeOf(e)}`, { defaultValue: t("workshop.agent.saveErr.generic") }) });
      return false;
    } finally {
      setSaving(false);
    }
  }

  const input = "mt-1 w-full rounded-xl border-2 border-line bg-surface px-3 py-2 outline-none focus:border-accent";
  const aasanByName = new Map(data.aasan_tools.map((x) => [x.name, x]));
  const aasanList = [...AASAN_TOOLS.filter((n) => aasanByName.has(n)), ...data.aasan_tools.map((x) => x.name).filter((n) => !AASAN_TOOLS.includes(n))];

  return (
    <section className="space-y-4" aria-labelledby={`agent-title-${sessionId}`}>
      <Card className="space-y-5">
        <div className="flex items-start gap-3">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-accent/10 text-accent"><Bot className="h-6 w-6" aria-hidden /></span>
          <div className="min-w-0">
            <h2 id={`agent-title-${sessionId}`} className="font-display text-2xl font-extrabold">{t("workshop.agent.title")}</h2>
            <p className="text-muted">{t("workshop.agent.sub")}</p>
          </div>
        </div>

        <div className="space-y-3">
          <StepHeading n={1} title={t("workshop.agent.step1")} sub={t("workshop.agent.step1Sub")} />
          <label className="block">
            <span className="text-sm font-medium">{t("workshop.agent.name")}</span>
            <input value={draft.name} onChange={(e) => set({ name: e.target.value })} maxLength={AGENT_NAME_MAX} placeholder={t("workshop.agent.namePh")} className={input} />
          </label>
          <label className="block">
            <span className="text-sm font-medium">{t("workshop.agent.role")}</span>
            <textarea value={draft.role} onChange={(e) => set({ role: e.target.value })} maxLength={AGENT_ROLE_MAX} rows={5} placeholder={t("workshop.agent.rolePh")} className={input} />
            <span className="mt-1 block text-right text-xs text-muted">{t("workshop.agent.chars", { n: draft.role.length, max: AGENT_ROLE_MAX })}</span>
          </label>
          <label className="block">
            <span className="text-sm font-medium">{t("workshop.agent.starter")}</span>
            <input value={draft.starter} onChange={(e) => set({ starter: e.target.value })} maxLength={AGENT_STARTER_MAX} placeholder={t("workshop.agent.starterPh")} className={input} />
          </label>
        </div>

        <div className="space-y-3">
          <StepHeading n={2} title={t("workshop.agent.step2")} sub={t("workshop.agent.step2Sub")} />
          <p className={cn("text-sm font-semibold", full ? "text-accent" : "text-muted")} data-testid="tool-count">{t("workshop.agent.toolCount", { n: count, max: AGENT_MAX_TOOLS })}</p>
          {full && <p role="status" className="text-sm text-muted">{t("workshop.agent.toolLimit")}</p>}
          <ul className="space-y-2" aria-label={t("workshop.agent.step2")}>
            {aasanList.map((name) => {
              const on = draft.aasan_tools.includes(name);
              const known = AASAN_TOOLS.includes(name);
              return (
                <ToolRow key={name} name={name} checked={on} disabled={!on && full}
                  title={known ? t(`workshop.agent.tools.${name}.name`) : name}
                  description={known ? t(`workshop.agent.tools.${name}.desc`) : aasanByName.get(name)?.description ?? ""}
                  onChange={(v) => set({ aasan_tools: toggle(draft.aasan_tools, name, v) })} />
              );
            })}
          </ul>
        </div>

        <div className="space-y-3">
          <StepHeading n={3} title={t("workshop.agent.step3")} sub={t("workshop.agent.step3Sub")} />
          <p className="flex gap-2 rounded-xl bg-good/10 px-3 py-2.5 text-sm"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-good" aria-hidden /> {t("workshop.agent.safety")}</p>
          {!!data.servers.length && (
            <ul className="space-y-3">
              {data.servers.map((s) => (
                <ServerCard key={String(s.id)} sessionId={sessionId} server={s} draft={draft.enabled[String(s.id)] ?? []} full={full}
                  autoApproved={data.auto_approve?.[String(s.id)] ?? []} onChanged={reload}
                  onToggle={(tool, on) => set({ enabled: { ...draft.enabled, [String(s.id)]: toggle(draft.enabled[String(s.id)] ?? [], tool, on) } })} />
              ))}
            </ul>
          )}
          {data.servers.length >= AGENT_MAX_SERVERS
            ? <p className="text-sm text-muted">{t("workshop.agent.maxServers", { count: AGENT_MAX_SERVERS })}</p>
            : <ConnectForm sessionId={sessionId} onConnected={reload} />}
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
          <Button onClick={() => void save()} loading={saving} className="py-3"><Save className="h-5 w-5" aria-hidden /> {t("workshop.agent.save")}</Button>
          {saveMsg ? <p role={saveMsg.ok ? "status" : "alert"} className={cn("text-sm font-medium", saveMsg.ok ? "text-good" : "text-bad")}>{saveMsg.text}</p>
            : dirty && <p className="text-sm text-muted">{t("workshop.agent.unsaved")}</p>}
        </div>
      </Card>

      <Card className="space-y-3">
        <StepHeading n={4} title={t("workshop.agent.step4")} sub={t("workshop.agent.step4Sub")} />
        <TestChat sessionId={sessionId} runsLeft={runsLeft} setRunsLeft={setRunsLeft} starter={draft.starter} onAlways={reload}
          beforeRun={async () => (dirty ? save() : true)} initial={restore(data.chat, data.pending)} />
      </Card>

      <McpCard mcp={data.mcp} />
    </section>
  );
}
