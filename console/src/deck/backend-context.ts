import { getLocale } from "../i18n";
import { ROUTE_ACTION_HINTS } from "./answerer";
import type { AnswerVerification, BackendTurn } from "./backend-types";
import type { ViewSnapshot } from "./context";
import { normalizeIncidentBinding } from "./conversation-sessions";
import { getDeckUser } from "./deck-user";
import type { IncidentConversationBinding } from "./open-deck";

function viewContextWithUser(snapshot: ViewSnapshot | null): Record<string, unknown> {
  const base: Record<string, unknown> = snapshot ? { ...snapshot } : {};
  const user = getDeckUser();
  if (user) base._user = user;
  if (snapshot?.routeId) {
    const hint = ROUTE_ACTION_HINTS[snapshot.routeId];
    if (hint) base._route_actions = hint;
  }
  base._locale = getLocale();
  return base;
}

function toBackendHistory(history: readonly BackendTurn[]): BackendTurn[] {
  return history.slice(-8).map((turn) => ({
    role: turn.role,
    content: turn.content,
  }));
}

export function createBackendRequestPayload(
  prompt: string,
  snapshot: ViewSnapshot | null,
  history: readonly BackendTurn[],
  sessionId: string | undefined,
  requestId?: string,
  binding?: IncidentConversationBinding,
): Record<string, unknown> {
  const normalizedBinding = normalizeIncidentBinding(binding);
  return {
    ...(requestId === undefined ? {} : { request_id: requestId }),
    prompt,
    session_id: sessionId,
    ...(normalizedBinding ? {
      conversation_context: {
        kind: normalizedBinding.kind,
        incident_id: normalizedBinding.incidentId,
        correlation_id: normalizedBinding.correlationId,
        ...(normalizedBinding.selectedAgent
          ? { selected_agent: normalizedBinding.selectedAgent }
          : {}),
      },
    } : {}),
    view_context: viewContextWithUser(snapshot),
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
      citations.push({ label: `records.${key}`, value: `${rows.length} row(s)` });
    }
  }
  return citations;
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
