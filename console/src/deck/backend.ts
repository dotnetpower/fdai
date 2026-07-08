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
import { answer as deterministicAnswer, type Answer } from "./answerer";
import type { ViewSnapshot } from "./context";

export interface BackendTurn {
  readonly role: "user" | "assistant";
  readonly content: string;
}

/** One candidate's rolling stat from the latency-routed backend. */
export interface RouterCandidate {
  readonly deployment: string;
  readonly p50_ms: number | null;
  readonly samples: number;
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
        view_context: snapshot ?? {},
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
    // LLM replies do not carry structured citations yet; the deck falls
    // back to showing 4-6 facts from the snapshot as a "grounded on"
    // strip so the operator still sees what the model was told.
    citations: snapshot
      ? snapshot.facts.slice(0, 6).map((f) => ({
          label: f.key,
          value: f.value === null ? "-" : String(f.value),
        }))
      : [],
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
    const samples =
      typeof cr.samples === "number" && Number.isFinite(cr.samples) ? cr.samples : 0;
    candidates.push({ deployment, p50_ms: p50, samples });
  }
  return { chose, reason, candidates };
}
