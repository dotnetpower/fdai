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

import { answer as deterministicAnswer } from "./answerer";
import { createActionSubmitter } from "./backend-actions";
import {
  citationsForVerification,
  createBackendRequestPayload,
} from "./backend-context";
import { chatUrl, healthUrl, requestHeaders } from "./backend-endpoints";
import { createBackendHealthProbe } from "./backend-health";
import {
  extractNumber,
  extractString,
  parseAnswerVerification,
  parseDelegation,
  parseRouter,
  tokenSuffix,
} from "./backend-normalizers";
import {
  parseAnswerPlan,
  parseAnswerPlanning,
  parseGroundedCodeArtifacts,
} from "./backend-parsers";
import type { ViewSnapshot } from "./context";
import type {
  BackendTurn,
  ProgressiveAnswer,
} from "./backend-types";
import type { IncidentConversationBinding } from "./open-deck";

export { setChatAuth } from "./auth";
export { renderActionResult, type ActionSubmitResult } from "./backend-actions";
export {
  parseAnswerPlan,
  parseAnswerPlanning,
  parseGroundedCodeArtifacts,
} from "./backend-parsers";
export { askBackendStream, fallbackTypewriter, streamBurstPacer } from "./backend-stream";
export type * from "./backend-types";

/**
 * Ping the chat backend's health endpoint. Returns a descriptor even
 * on failure - callers can render "offline" without a try/catch.
 */
export const probeBackend = createBackendHealthProbe(
  healthUrl,
  () => requestHeaders(),
  parseRouter,
);

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
  sessionId?: string,
  binding?: IncidentConversationBinding,
): Promise<ProgressiveAnswer> {
  let response: Response;
  try {
    response = await fetch(chatUrl(), {
      method: "POST",
      headers: await requestHeaders(true),
      body: JSON.stringify(
        createBackendRequestPayload(prompt, snapshot, history, sessionId, undefined, binding),
      ),
      credentials: "omit",
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
  const explicitSource = extractString(payload, "source");
  const latencyMs = extractNumber(payload, "latency_ms");
  const verification = parseAnswerVerification(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).verification
      : undefined,
  );
  const router = parseRouter(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).router
      : undefined,
  );
  const delegation = parseDelegation(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).delegation
      : undefined,
  );
  const answerPlan = parseAnswerPlan(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).answer_plan
      : undefined,
  );
  const answerPlanning = parseAnswerPlanning(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).answer_planning
      : undefined,
  );
  const codeArtifacts = parseGroundedCodeArtifacts(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).code_artifacts
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
  const source = explicitSource ?? (
    (latencyMs !== null && latencyMs >= 0
      ? `llm:${chosen} · ${latencyMs}ms`
      : `llm:${chosen}`) +
    tokenSuffix(
      typeof payload === "object" && payload !== null
        ? (payload as Record<string, unknown>).usage
        : undefined,
    )
  );
  const base = {
    text: answerText,
    // LLM replies do not carry structured citations; the deck grounds the
    // reply on the snapshot the model was given (see snapshotCitations).
    citations: citationsForVerification(snapshot, verification),
    followUps: [],
    source,
    ...(verification ? { verification } : {}),
  };
  return {
    ...base,
    ...(router ? { router } : {}),
    ...(delegation ? { delegation } : {}),
    ...(answerPlan ? { answerPlan } : {}),
    ...(answerPlanning ? { answerPlanning } : {}),
    ...(codeArtifacts.length > 0 ? { codeArtifacts } : {}),
  };
}

export const submitAction = createActionSubmitter(chatUrl, () => requestHeaders(true));
