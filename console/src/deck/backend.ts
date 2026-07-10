/**
 * Chat backend client - POST /chat with graceful fallback.
 *
 * Single responsibility: turn a (prompt, snapshot, history) call into
 * an HTTP round-trip and normalise the reply / failure so the deck UI
 * can render either a real LLM answer or the deterministic answerer's
 * fallback without branching on transport details.
 *
 * The client also exposes a lightweight preflight (``probeBackend``)
 * that hits ``GET /chat/health`` once. The deck header renders the
 * returned descriptor as a status badge (``LLM ready · gpt-4o-mini``
 * or ``deterministic fallback``) so the operator sees the mode BEFORE
 * asking the first question - matching the "LLM by default" contract.
 */

import { loadConfig } from "../config";
import { getLocale } from "../i18n";
import { answer as deterministicAnswer, ROUTE_ACTION_HINTS, type Answer } from "./answerer";
import type { ViewSnapshot } from "./context";
import { getDeckUser } from "./deck-user";

/** Build the `view_context` sent to the chat backend: the screen snapshot plus
 *  the signed-in operator's identity/roles (`_user`) so the narrator can answer
 *  capability questions, plus the per-route action hint (`_route_actions`) so
 *  'what can I do here?' from the LLM matches the deterministic fallback and
 *  is grounded (never invented), plus the operator's active locale (`_locale`)
 *  so the L3 narrator renders the final answer in that language (the pipeline
 *  itself stays English - see language.instructions.md L3). Read-only,
 *  informational - see deck-user.ts. */
function viewContextWithUser(snapshot: ViewSnapshot | null): Record<string, unknown> {
  const base: Record<string, unknown> = snapshot ? { ...snapshot } : {};
  const user = getDeckUser();
  if (user) base._user = user;
  if (snapshot?.routeId) {
    const hint = ROUTE_ACTION_HINTS[snapshot.routeId];
    if (hint) base._route_actions = hint;
  }
  // Locale propagation: the backend prepends a locale directive only when
  // the tag is non-empty and not English (byte-identical default for
  // English operators), so passing `en` here is a safe no-op.
  base._locale = getLocale();
  return base;
}

export interface BackendTurn {
  readonly role: "user" | "assistant";
  readonly content: string;
}

/** One candidate's rolling stat from the latency-routed backend. */
export interface RouterCandidate {
  readonly deployment: string;
  readonly p50_ms: number | null;
  readonly p95_ms: number | null;
  readonly samples: number;
  /** Raw rolling window (most-recent last) - drives the sparkline strip. */
  readonly history_ms: readonly number[];
}

/** Router snapshot attached to a chat reply / health descriptor. */
export interface RouterSnapshot {
  readonly chose: string;
  readonly reason: string;
  readonly candidates: readonly RouterCandidate[];
}

export interface BackendReply {
  readonly text: string;
  /** ``"llm:<model> · <N>ms"`` when the reply came from the server, else ``"deterministic"``. */
  readonly source: string;
  /** Present when the server wired the latency-routed backend. */
  readonly router?: RouterSnapshot;
}

/** Health-check descriptor returned by ``GET /chat/health``. */
export interface BackendHealth {
  readonly available: boolean;
  readonly mode: string;
  readonly model: string | null;
  readonly endpoint: string | null;
  readonly router?: RouterSnapshot;
}

const OFFLINE_HEALTH: BackendHealth = {
  available: false,
  mode: "offline",
  model: null,
  endpoint: null,
};

function chatUrl(): string {
  const cfg = loadConfig();
  const base = cfg.readApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
  return `${base.replace(/\/$/, "")}/chat`;
}

function healthUrl(): string {
  return `${chatUrl()}/health`;
}

function streamUrl(): string {
  return `${chatUrl()}/stream`;
}

function toBackendHistory(history: readonly BackendTurn[]): BackendTurn[] {
  // Only user/assistant pairs, most recent 8 turns.
  return history.slice(-8).map((t) => ({ role: t.role, content: t.content }));
}

/**
 * Ping the chat backend's health endpoint. Returns a descriptor even
 * on failure - callers can render "offline" without a try/catch.
 */
export async function probeBackend(): Promise<BackendHealth> {
  let response: Response;
  try {
    response = await fetch(healthUrl(), { method: "GET" });
  } catch {
    return OFFLINE_HEALTH;
  }
  if (!response.ok) {
    return {
      available: false,
      mode: `unreachable (${response.status})`,
      model: null,
      endpoint: null,
    };
  }
  try {
    const payload = (await response.json()) as Partial<BackendHealth> & {
      router?: unknown;
    };
    const router = parseRouter(payload.router);
    const base: BackendHealth = {
      available: payload.available === true,
      mode: typeof payload.mode === "string" ? payload.mode : "unknown",
      model: typeof payload.model === "string" ? payload.model : null,
      endpoint: typeof payload.endpoint === "string" ? payload.endpoint : null,
    };
    return router ? { ...base, router } : base;
  } catch {
    return OFFLINE_HEALTH;
  }
}

/**
 * Ask the chat backend. Always tries the backend first; falls back to
 * the deterministic answerer per-turn when the request fails. Never
 * caches failures permanently - transient outages self-heal on the
 * next attempt.
 */
export async function askBackend(
  prompt: string,
  snapshot: ViewSnapshot | null,
  history: readonly BackendTurn[],
): Promise<Answer & { readonly source: string; readonly router?: RouterSnapshot }> {
  let response: Response;
  try {
    response = await fetch(chatUrl(), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        prompt,
        view_context: viewContextWithUser(snapshot),
        history: toBackendHistory(history),
      }),
    });
  } catch {
    const local = deterministicAnswer(prompt, snapshot);
    return { ...local, source: "deterministic (offline)" };
  }

  if (response.status === 404 || response.status === 501) {
    // Endpoint not wired on this deployment (no upstream configured).
    const local = deterministicAnswer(prompt, snapshot);
    return { ...local, source: "deterministic (LLM not configured)" };
  }

  if (response.status === 422) {
    // Prompt refused by the upstream content/jailbreak filter - a safe,
    // expected block (not an outage). Label it distinctly.
    const local = deterministicAnswer(prompt, snapshot);
    return { ...local, source: "deterministic (blocked by content policy)" };
  }

  if (!response.ok) {
    // Upstream error - deterministic fallback for this turn only. We do
    // NOT cache: transient upstream hiccups must self-heal.
    const local = deterministicAnswer(prompt, snapshot);
    return { ...local, source: `deterministic (backend ${response.status})` };
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    const local = deterministicAnswer(prompt, snapshot);
    return { ...local, source: "deterministic (bad JSON)" };
  }

  const answerText = extractString(payload, "answer");
  const model = extractString(payload, "model") ?? "llm";
  const latencyMs = extractNumber(payload, "latency_ms");
  const router = parseRouter(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).router
      : undefined,
  );
  if (answerText === null) {
    const local = deterministicAnswer(prompt, snapshot);
    return { ...local, source: "deterministic (no answer field)" };
  }
  // Compose the source badge. Router pick wins over the plain ``model``
  // field so the operator always sees the deployment that actually served
  // the turn (they can differ if the backend echoes a canonical name).
  const chosen = router?.chose ?? model;
  const source =
    latencyMs !== null && latencyMs >= 0
      ? `llm:${chosen} · ${latencyMs}ms`
      : `llm:${chosen}`;
  const base = {
    text: answerText,
    // LLM replies do not carry structured citations; the deck grounds the
    // reply on the snapshot the model was given (see snapshotCitations).
    citations: snapshotCitations(snapshot),
    followUps: [],
    source,
  };
  return router ? { ...base, router } : base;
}

/** Synthesize the client-side "grounded on" citations from the snapshot -
 *  LLM replies do not carry structured citations, so the deck grounds on what
 *  the model was told: the screen it read, the facts on it, and the record
 *  collections it could search. The deck (GroundedReply) then narrows these to
 *  the ones the answer actually references. */
function snapshotCitations(
  snapshot: ViewSnapshot | null,
): readonly { readonly label: string; readonly value?: string }[] {
  if (!snapshot) return [];
  const cites: { readonly label: string; readonly value?: string }[] = [
    // Always cite the screen the answer is grounded on (kept even when the
    // answer references none of the individual facts).
    { label: "screen", value: `${snapshot.routeLabel} - ${snapshot.headline}` },
  ];
  for (const f of snapshot.facts.slice(0, 12)) {
    cites.push({ label: f.key, value: f.value === null ? "-" : String(f.value) });
  }
  const records = snapshot.records ?? {};
  for (const [key, rows] of Object.entries(records)) {
    if (Array.isArray(rows) && rows.length > 0) {
      cites.push({ label: `records.${key}`, value: `${rows.length} row(s)` });
    }
  }
  return cites;
}

/** Callbacks for :func:`askBackendStream`. */
export interface StreamCallbacks {
  /** Fired for each streamed token delta (append to the live reply). */
  readonly onToken: (delta: string) => void;
  /** Optional signal; abort to stop the stream and keep whatever streamed so far. */
  readonly signal?: AbortSignal;
}

/**
 * Ask the chat backend over SSE (`POST /chat/stream`), streaming tokens as
 * they arrive. Resolves to the same shape as :func:`askBackend` once the
 * terminal `done` frame lands. Falls back to the deterministic answerer -
 * emitting the whole answer through `onToken` once - on any transport error
 * or an `error` frame, so the deck always renders something.
 */
export async function askBackendStream(
  prompt: string,
  snapshot: ViewSnapshot | null,
  history: readonly BackendTurn[],
  cb: StreamCallbacks,
): Promise<Answer & { readonly source: string; readonly router?: RouterSnapshot }> {
  const fallback = (why: string): Answer & { readonly source: string } => {
    const local = deterministicAnswer(prompt, snapshot);
    cb.onToken(local.text);
    return { ...local, source: `deterministic (${why})` };
  };

  const stopped = (partial: string): Answer & { readonly source: string } => ({
    text: partial.length > 0 ? partial : "Stopped before any answer arrived.",
    citations: snapshotCitations(snapshot),
    followUps: [],
    source: "stopped",
  });

  let response: Response;
  try {
    response = await fetch(streamUrl(), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        prompt,
        view_context: viewContextWithUser(snapshot),
        history: toBackendHistory(history),
      }),
      signal: cb.signal ?? null,
    });
  } catch {
    if (cb.signal?.aborted) return stopped("");
    return fallback("offline");
  }
  if (response.status === 404 || response.status === 501) {
    return fallback("LLM not configured");
  }
  if (response.status === 422) {
    // The upstream content/jailbreak filter refused the prompt. This is a safe,
    // expected block (not an outage); label it distinctly so the operator sees
    // why rather than a generic transient error.
    return fallback("blocked by content policy");
  }
  if (!response.ok || response.body === null) {
    return fallback(`backend ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answerText = "";
  let doneData: Record<string, unknown> | null = null;
  let errored = false;

  const handleFrame = (frame: string): void => {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(dataLines.join("\n"));
    } catch {
      return;
    }
    const obj =
      typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : {};
    if (event === "token") {
      const delta = typeof obj.delta === "string" ? obj.delta : "";
      if (delta) {
        answerText += delta;
        cb.onToken(delta);
      }
    } else if (event === "done") {
      doneData = obj;
    } else if (event === "error") {
      errored = true;
    }
  };

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        handleFrame(buffer.slice(0, idx));
        buffer = buffer.slice(idx + 2);
      }
    }
  } catch {
    if (cb.signal?.aborted) return stopped(answerText);
    if (answerText === "") return fallback("stream interrupted");
  }
  if (buffer.trim().length > 0) handleFrame(buffer);

  if (errored && answerText === "") return fallback("stream error");
  if (answerText === "" && doneData === null) return fallback("empty stream");

  const done: Record<string, unknown> = doneData ?? {};
  const finalText = typeof done.answer === "string" && done.answer ? done.answer : answerText;
  const model = typeof done.model === "string" ? done.model : "llm";
  const latencyMs =
    typeof done.latency_ms === "number" && Number.isFinite(done.latency_ms)
      ? done.latency_ms
      : null;
  const router = parseRouter(done.router);
  const chosen = router?.chose ?? model;
  const source =
    latencyMs !== null && latencyMs >= 0 ? `llm:${chosen} · ${latencyMs}ms` : `llm:${chosen}`;
  const base: Answer & { readonly source: string } = {
    text: finalText,
    citations: snapshotCitations(snapshot),
    followUps: [],
    source,
  };
  return router ? { ...base, router } : base;
}

function extractString(payload: unknown, key: string): string | null {
  if (typeof payload !== "object" || payload === null) return null;
  const v = (payload as Record<string, unknown>)[key];
  return typeof v === "string" ? v : null;
}

function extractNumber(payload: unknown, key: string): number | null {
  if (typeof payload !== "object" || payload === null) return null;
  const v = (payload as Record<string, unknown>)[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function parseRouter(raw: unknown): RouterSnapshot | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const r = raw as Record<string, unknown>;
  const chose = typeof r.chose === "string" ? r.chose : null;
  if (chose === null) return undefined;
  const reason = typeof r.reason === "string" ? r.reason : "";
  const rawCandidates = Array.isArray(r.candidates) ? r.candidates : [];
  const candidates: RouterCandidate[] = [];
  for (const c of rawCandidates) {
    if (typeof c !== "object" || c === null) continue;
    const cr = c as Record<string, unknown>;
    const deployment = typeof cr.deployment === "string" ? cr.deployment : null;
    if (deployment === null) continue;
    const p50 =
      typeof cr.p50_ms === "number" && Number.isFinite(cr.p50_ms) ? cr.p50_ms : null;
    const p95 =
      typeof cr.p95_ms === "number" && Number.isFinite(cr.p95_ms) ? cr.p95_ms : null;
    const samples =
      typeof cr.samples === "number" && Number.isFinite(cr.samples) ? cr.samples : 0;
    const historyRaw = Array.isArray(cr.history_ms) ? cr.history_ms : [];
    const history: number[] = [];
    for (const h of historyRaw) {
      if (typeof h === "number" && Number.isFinite(h) && h >= 0) history.push(h);
    }
    candidates.push({ deployment, p50_ms: p50, p95_ms: p95, samples, history_ms: history });
  }
  return { chose, reason, candidates };
}

// ---------------------------------------------------------------------------
// Action submission (POST /chat/action) - propose, never execute
// ---------------------------------------------------------------------------

function actionUrl(): string {
  return `${chatUrl()}/action`;
}

/** A stable idempotency key for one submit attempt, so a duplicated / retried
 *  request collapses server-side (Huginn dedup) instead of enqueuing a second
 *  action. Uses crypto.randomUUID when available, else a timestamp+random. */
function newIdempotencyKey(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c?.randomUUID) return `act-${c.randomUUID()}`;
  return `act-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Result of submitting an operator command to the typed pipeline. */
export interface ActionSubmitResult {
  /** True when the proposal was accepted and published for judgment. */
  readonly submitted: boolean;
  /** HTTP status (0 on a transport error). */
  readonly status: number;
  /** The ActionType the command mapped to, when submitted. */
  readonly actionType?: string;
  /** The correlation id to track the proposal (Trace panel / audit). */
  readonly correlationId?: string;
  /** Why it was refused: `rbac_capability` | `unmapped_action_intent` |
   *  `not_wired` | `error`. */
  readonly reason?: string;
  /** The capability the operator was missing (for `rbac_capability`). */
  readonly requiredCapability?: string;
}

/**
 * Submit an operator command to `POST /chat/action`. The endpoint publishes an
 * `ActionProposal` into the typed pipeline (Forseti judges, Var approves a
 * high-risk one, Thor executes shadow-first) - it never executes here. RBAC is
 * enforced server-side from the validated token; a Reader gets `403`.
 *
 * Never throws: a transport error or an unwired endpoint resolves to a
 * `submitted: false` result the deck can render as a plain message.
 */
export async function submitAction(
  prompt: string,
  sessionId: string | null,
): Promise<ActionSubmitResult> {
  let response: Response;
  try {
    response = await fetch(actionUrl(), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        prompt,
        session_id: sessionId ?? undefined,
        idempotency_key: newIdempotencyKey(),
      }),
    });
  } catch {
    return { submitted: false, status: 0, reason: "error" };
  }
  if (response.status === 404 || response.status === 501) {
    return { submitted: false, status: response.status, reason: "not_wired" };
  }
  let payload: Record<string, unknown> = {};
  try {
    const parsed = await response.json();
    if (typeof parsed === "object" && parsed !== null) {
      payload = parsed as Record<string, unknown>;
    }
  } catch {
    /* fall through - use the status only */
  }
  const submitted = payload.submitted === true;
  const result: ActionSubmitResult = {
    submitted,
    status: response.status,
    ...(typeof payload.action_type === "string" ? { actionType: payload.action_type } : {}),
    ...(typeof payload.correlation_id === "string"
      ? { correlationId: payload.correlation_id }
      : {}),
    ...(typeof payload.reason === "string" ? { reason: payload.reason } : {}),
    ...(typeof payload.required_capability === "string"
      ? { requiredCapability: payload.required_capability }
      : {}),
  };
  return result;
}

/** A plain-language deck message describing an action-submit result. */
export function renderActionResult(r: ActionSubmitResult): string {
  if (r.submitted) {
    return (
      `Submitted "${r.actionType ?? "action"}" to the pipeline for judgment. ` +
      `Nothing runs until Forseti judges it and (if high-risk) an approver signs off - ` +
      `execution is shadow-first. Track it by correlation ${r.correlationId ?? "-"} in the Trace panel.`
    );
  }
  switch (r.reason) {
    case "rbac_capability":
      return (
        "Your role can't submit actions - that needs the Contributor capability " +
        `(${r.requiredCapability ?? "author-draft-pr"}). This console stays read-only for you.`
      );
    case "unmapped_action_intent":
      return "I recognised that as a command, but it maps to no known action yet, so I did not submit it.";
    case "not_wired":
      return "Action submission is not enabled on this deployment (read-only console).";
    default:
      return "I could not submit that action (the action endpoint did not respond).";
  }
}
