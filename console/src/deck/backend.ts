/**
 * Chat backend client - POST /chat with explicit unavailable results.
 *
 * Single responsibility: turn a (prompt, snapshot, history) call into
 * an HTTP round-trip and normalise the reply / failure so the deck UI
 * can render either a model-backed answer or a typed unavailable result
 * without branching on transport details.
 *
 * The client also exposes a lightweight preflight (``probeBackend``)
 * that hits ``GET /chat/health`` once. The deck header renders the
 * returned descriptor as a status badge (``LLM ready · gpt-4o-mini``
 * or unavailable) so the operator sees the mode BEFORE
 * asking the first question - matching the "LLM by default" contract.
 */

import { createActionConfirmer, createActionSubmitter } from "./backend-actions";
import {
  citationsForVerification,
  createBackendRequestPayload,
} from "./backend-context";
import { chatUrl, healthUrl, requestHeaders } from "./backend-endpoints";
import { createBackendHealthProbe } from "./backend-health";
import { semanticUnavailable } from "./backend-unavailable";
import {
  extractNumber,
  extractString,
  parseAnswerVerification,
  parseDelegation,
  parseEvidenceFreshnessContext,
  isSemanticDirectResponseSource,
  parseRouter,
  parseResourceContext,
  semanticDirectResponseSource,
  tokenSuffix,
} from "./backend-normalizers";
import {
  parseAnswerPlan,
  parseAnswerPlanning,
  parseGroundedCodeArtifacts,
  parseIncidentCandidates,
  parseModelTrace,
  parseTurnTiming,
} from "./backend-parsers";
import type { ViewSnapshot } from "./context";
import type {
  BackendTurn,
  ProgressiveAnswer,
} from "./backend-types";
import type { IncidentConversationBinding } from "./open-deck";
import { normalizeIncidentBinding } from "./conversation-sessions";
import { parseTrajectoryDetail } from "./trajectory-detail";
import { parseIntentGraph, parseIntentGraphEvidence } from "./intent-graph";
import { parsePresentationArtifact } from "./presentation-artifact";
import { chartArtifactText } from "./rich-parse";

export { setChatAuth } from "./auth";
export { renderActionResult, type ActionSubmitResult } from "./backend-actions";
export {
  parseAnswerPlan,
  parseAnswerPlanning,
  parseGroundedCodeArtifacts,
  parseIncidentCandidates,
  parseModelTrace,
  parseTurnTiming,
} from "./backend-parsers";
export {
  askBackendStream,
  fallbackTypewriter,
  streamBurstPacer,
  streamProtocolMetricsSnapshot,
} from "./backend-stream";
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
 * Ask the chat backend. A failed model-backed request returns unavailable
 * without attempting to infer meaning from the operator's words. Failures
 * are not cached, so a later attempt can recover normally.
 */
export async function askBackend(
  prompt: string,
  snapshot: ViewSnapshot | null,
  history: readonly BackendTurn[],
  sessionId?: string,
  binding?: IncidentConversationBinding,
  targetAgent?: string,
): Promise<ProgressiveAnswer> {
  let response: Response;
  try {
    response = await fetch(chatUrl(), {
      method: "POST",
      headers: await requestHeaders(true),
      body: JSON.stringify(
        createBackendRequestPayload(
          prompt,
          snapshot,
          history,
          sessionId,
          undefined,
          binding,
          undefined,
          targetAgent,
        ),
      ),
      credentials: "omit",
    });
  } catch {
    return semanticUnavailable("offline");
  }

  if (response.status === 404 || response.status === 501) {
    // Endpoint not wired on this deployment (no upstream configured).
    return semanticUnavailable("model not configured");
  }

  if (response.status === 422) {
    // Prompt refused by the upstream content/jailbreak filter - a safe,
    // expected block (not an outage). Label it distinctly.
    return semanticUnavailable("blocked by content policy");
  }

  if (!response.ok) {
    return semanticUnavailable(`backend ${response.status}`);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return semanticUnavailable("bad JSON");
  }

  const payloadRecord = typeof payload === "object" && payload !== null
    ? payload as Record<string, unknown>
    : undefined;
  const model = extractString(payload, "model") ?? "llm";
  const explicitSource = extractString(payload, "source");
  const latencyMs = extractNumber(payload, "latency_ms");
  const verification = parseAnswerVerification(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).verification
      : undefined,
  );
  const presentationArtifact = parsePresentationArtifact(
    payloadRecord?.presentation_artifact,
    verification,
  );
  const conversationBinding = normalizeIncidentBinding(payloadRecord?.conversation_context);
  const canonicalAnswer = extractString(payload, "answer");
  const answerText = presentationArtifact
    ? canonicalAnswer
    : chartArtifactText(payloadRecord?.chart_artifact) ?? canonicalAnswer;
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
  const incidentCandidates = parseIncidentCandidates(payloadRecord?.incident_candidates);
  const resourceContext = parseResourceContext(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).resource_context
      : undefined,
  );
  const evidenceFreshnessContext = parseEvidenceFreshnessContext(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).evidence_freshness_context
      : undefined,
  );
  const modelTrace = parseModelTrace(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).model_trace
      : undefined,
  );
  const turnTiming = parseTurnTiming(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).turn_timing
      : undefined,
  );
  const trajectoryDetail = parseTrajectoryDetail(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).trajectory_detail
      : undefined,
  );
  const intentGraph = parseIntentGraph(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).intent_graph
      : undefined,
  );
  const intentGraphEvidence = parseIntentGraphEvidence(
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).intent_graph_evidence
      : undefined,
  );
  if (answerText === null) {
    return semanticUnavailable("no answer field");
  }
  // Compose the source badge. Router pick wins over the plain ``model``
  // field so the operator always sees the deployment that actually served
  // the turn (they can differ if the backend echoes a canonical name).
  const chosen = router?.chose ?? model;
  const usage = typeof payload === "object" && payload !== null
    ? (payload as Record<string, unknown>).usage
    : undefined;
  const directResponse = isSemanticDirectResponseSource(explicitSource);
  const source = directResponse
    ? semanticDirectResponseSource(chosen, latencyMs, usage)
    : explicitSource ?? (
    (latencyMs !== null && latencyMs >= 0
      ? `llm:${chosen} · ${latencyMs}ms`
      : `llm:${chosen}`) +
    tokenSuffix(usage)
  );
  const base = {
    text: answerText,
    // LLM replies do not carry structured citations; the deck grounds the
    // reply on the snapshot the model was given (see snapshotCitations).
    citations: directResponse ? [] : citationsForVerification(snapshot, verification),
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
    ...(incidentCandidates.length > 0 ? { incidentCandidates } : {}),
    ...(presentationArtifact ? { presentationArtifact } : {}),
    ...(conversationBinding ? { conversationBinding } : {}),
    ...(resourceContext ? { resourceContext } : {}),
    ...(evidenceFreshnessContext ? { evidenceFreshnessContext } : {}),
    ...(modelTrace ? { modelTrace } : {}),
    ...(turnTiming ? { turnTiming } : {}),
    ...(trajectoryDetail ? { trajectoryDetail } : {}),
    ...(intentGraph ? { intentGraph } : {}),
    ...(intentGraphEvidence ? {
      intentGraphEvidence,
      evidenceMode: intentGraphEvidence.evidence_mode,
    } : {}),
  };
}

export const submitAction = createActionSubmitter(chatUrl, () => requestHeaders(true));
export const confirmActionDraft = createActionConfirmer(chatUrl, () => requestHeaders(true));
