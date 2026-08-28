import { readConsolePreferences } from "../preferences";
import { ROUTE_ACTION_HINTS } from "./answerer";
import type { AnswerVerification, BackendTurn } from "./backend-types";
import type { ChatAttachment } from "./composer-attachment-store";
import type { ViewSnapshot } from "./context";
import { normalizeIncidentBinding } from "./conversation-sessions";
import { getDeckUser } from "./deck-user";
import type { IncidentConversationBinding } from "./open-deck";

const HANGUL = /[가-힣]/u;

function responseLocale(prompt: string): "en" | "ko" {
  return HANGUL.test(prompt) ? "ko" : "en";
}

/**
 * Strips `contextIdentity`: the server-verifiable selection identity carries
 * principal, scope, and release digest capability metadata that MUST reach
 * Operator only as the opaque `selection_token` forwarded via
 * `contextBinding()`/`conversation_context` (see contextBinding below). It
 * MUST NOT also be replicated into the narrator-facing `view_context`.
 */
function narratorViewFields(snapshot: ViewSnapshot): Record<string, unknown> {
  const { contextIdentity: _contextIdentity, ...rest } = snapshot;
  return { ...rest };
}

function viewContextWithUser(
  snapshot: ViewSnapshot | null,
  locale: "en" | "ko",
): Record<string, unknown> {
  const base: Record<string, unknown> = snapshot ? narratorViewFields(snapshot) : {};
  if (typeof window !== "undefined") base._screen_path = window.location.pathname;
  const user = getDeckUser();
  if (user) base._user = user;
  if (snapshot?.routeId) {
    const hint = ROUTE_ACTION_HINTS[snapshot.routeId];
    if (hint) base._route_actions = hint;
  }
  base._locale = locale;
  return base;
}

function toBackendHistory(history: readonly BackendTurn[]): BackendTurn[] {
  return history.slice(-8).map((turn) => ({
    role: turn.role,
    content: turn.content,
  }));
}

function latestResourceContext(history: readonly BackendTurn[]) {
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const turn = history[index];
    if (turn?.role === "assistant") return turn.resourceContext;
  }
  return undefined;
}

function latestEvidenceFreshnessContext(history: readonly BackendTurn[]) {
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const turn = history[index];
    if (turn?.role === "assistant") return turn.evidenceFreshnessContext;
  }
  return undefined;
}

function latestConversationBinding(history: readonly BackendTurn[]) {
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const turn = history[index];
    if (turn?.role === "assistant") return normalizeIncidentBinding(turn.conversationBinding);
  }
  return null;
}

function contextBinding(snapshot: ViewSnapshot | null): Record<string, unknown> | undefined {
  const identity = snapshot?.contextIdentity;
  if (
    !identity ||
    identity.resourceIds.length === 0 ||
    identity.complete !== true ||
    !identity.principalId ||
    !identity.principalScopeDigest ||
    !identity.ontologyReleaseDigest ||
    !identity.sourceGeneration ||
    !identity.selectionDigest ||
    !identity.selectionToken
  ) return undefined;
  return {
    kind: identity.kind,
    selection_token: identity.selectionToken,
  };
}

export function createBackendRequestPayload(
  prompt: string,
  snapshot: ViewSnapshot | null,
  history: readonly BackendTurn[],
  sessionId: string | undefined,
  requestId?: string,
  binding?: IncidentConversationBinding,
  attachments?: readonly ChatAttachment[],
  targetAgent?: string,
  semanticPlanningProfile?: "interactive" | "golden_campaign_no_t2",
): Record<string, unknown> {
  const locale = responseLocale(prompt);
  const includeModelTrace = readConsolePreferences().showModelTrace;
  const normalizedBinding = normalizeIncidentBinding(binding) ?? latestConversationBinding(history);
  const resourceContext = latestResourceContext(history);
  const evidenceFreshnessContext = latestEvidenceFreshnessContext(history);
  const selectedContext = contextBinding(snapshot);
  return {
    ...(requestId === undefined
      ? {}
      : { request_id: requestId, idempotency_key: requestId }),
    ...(includeModelTrace ? { include_model_trace: true } : {}),
    prompt,
    locale,
    session_id: sessionId,
    ...(semanticPlanningProfile && semanticPlanningProfile !== "interactive"
      ? { semantic_planning_profile: semanticPlanningProfile }
      : {}),
    ...(targetAgent ? { target_agent: targetAgent } : {}),
    ...(resourceContext ? { resource_context: resourceContext } : {}),
    ...(evidenceFreshnessContext
      ? { evidence_freshness_context: evidenceFreshnessContext }
      : {}),
    ...(attachments && attachments.length > 0
      ? {
          attachments: attachments.map((attachment) => ({
            id: attachment.id,
            name: attachment.name,
            media_type: attachment.media_type,
            data_url: attachment.data_url,
          })),
        }
      : {}),
    ...(normalizedBinding
      ? {
          conversation_context: {
            kind: normalizedBinding.kind,
            incident_id: normalizedBinding.incidentId,
            correlation_id: normalizedBinding.correlationId,
            ...(normalizedBinding.selectedAgent
              ? { selected_agent: normalizedBinding.selectedAgent }
              : {}),
          },
        }
      : (selectedContext ? { conversation_context: selectedContext } : {})),
    view_context: viewContextWithUser(snapshot, locale),
    history: toBackendHistory(history),
  };
}

export function snapshotCitations(
  snapshot: ViewSnapshot | null,
): readonly { readonly label: string; readonly value?: string }[] {
  if (!snapshot) return [];
  const citations: { readonly label: string; readonly value?: string }[] = [
    { label: "screen", value: `${snapshot.routeLabel} - ${snapshot.headline}` },
  ];
  for (const fact of snapshot.facts.slice(0, 12)) {
    citations.push({
      label: fact.key,
      value: fact.value === null ? "-" : String(fact.value),
    });
  }
  const records = snapshot.records ?? {};
  for (const [key, rows] of Object.entries(records)) {
    if (Array.isArray(rows) && rows.length > 0) {
      citations.push({
        label: `records.${key}`,
        value: recordCitationPreview(rows),
      });
    }
  }
  return citations;
}

const MAX_RECORD_PREVIEW_FIELDS = 4;
const MAX_RECORD_PREVIEW_VALUE_CHARS = 72;
const MAX_RECORD_PREVIEW_CHARS = 320;

/** Summarize only browser-visible scalar fields from the first bounded record. */
export function recordCitationPreview(
  rows: readonly Record<string, unknown>[],
): string {
  const fields = Object.entries(rows[0] ?? {})
    .filter((entry): entry is [string, string | number | boolean] =>
      typeof entry[1] === "string" ||
      typeof entry[1] === "number" ||
      typeof entry[1] === "boolean")
    .slice(0, MAX_RECORD_PREVIEW_FIELDS)
    .map(([key, value]) => {
      const rendered = String(value);
      const bounded = rendered.length > MAX_RECORD_PREVIEW_VALUE_CHARS
        ? `${rendered.slice(0, MAX_RECORD_PREVIEW_VALUE_CHARS - 3)}...`
        : rendered;
      return `${key.replaceAll("_", " ")}: ${bounded}`;
    });
  const count = `${rows.length} row(s)`;
  if (fields.length === 0) return count;
  const preview = `${count} - ${fields.join("; ")}`;
  return preview.length > MAX_RECORD_PREVIEW_CHARS
    ? `${preview.slice(0, MAX_RECORD_PREVIEW_CHARS - 3)}...`
    : preview;
}

export function citationsForVerification(
  snapshot: ViewSnapshot | null,
  verification: AnswerVerification | undefined,
): readonly { readonly label: string; readonly value?: string }[] {
  if (verification && verification.evidence_refs.length > 0) {
    return verification.evidence_refs.map((reference, index) => ({
      label: `evidence.${index + 1}`,
      value: reference,
    }));
  }
  return snapshotCitations(snapshot);
}
